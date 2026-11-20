// PEPSI end-to-end driver: real input files, client and server as separate processes over TCP.
//
//   pepsi_e2e server --in server.csv --n <server set size> --port 1212 [--cmax 4096] [--threads T]
//   pepsi_e2e client --in client.csv --out result.csv --n <server set size> --host H --port 1212 [--cmax 4096]
//
// Both sides must be given the same public parameters (--n --cmax --alpha --lambda --hw --hash-index
// --map --seed); a fingerprint is checked in the handshake.
//
// Server: offline phase (hashing, plaintext encoding) before it starts listening; online phase
// (receive, homomorphic comparison, send) after the client connects.
// Client: key generation, cuckoo hashing, encoding and encryption, then send; decrypt and decode the answer.
#include <omp.h>

#include <cstdlib>
#include <random>

#include "common.h"
#include "net.h"

using namespace std;
using namespace seal;

static const char* kUsage =
    "usage: pepsi_e2e server|client --in FILE --n N [--out FILE] [--host H] [--port P] [--cmax C]\n"
    "       [--alpha 40] [--lambda auto|BITS] [--hw H] [--hash-index 0|1] [--map hash|identity]\n"
    "       [--seed S] [--threads T] [--precompute auto|0|1]\n";

static void emit(const string& tag, const string& json) { cout << tag << " " << json << endl; }

// ===================================================================== server
static int run_server(const Args& a) {
    PublicParams pp = make_pp(a);
    omp_set_num_threads((int)a.u64("threads", 1));
    emit("PSI_PARAMS", pp.json());
    MetricsOut m;
    m.str("role", "server");
    Stopwatch total, sw;

    // ---- offline 1: load + simple hashing (3 copies per element)
    vector<Item> items = read_items(a.require("in"));
    m.num("t_load_ms", sw.ms());
    if (items.size() != pp.n) throw invalid_argument("server file has " + to_string(items.size()) + " elements but --n is " + to_string(pp.n));

    sw.reset();
    vector<vector<uint64_t>> bins(pp.b);
    for (const Item& it : items) {
        Placement p = split_value(map_element(it.x, pp), pp);
        for (int i = 0; i < 3; ++i) bins[position(p, i, pp)].push_back(stored_value(p, i, pp));
    }
    size_t max_load = 0;
    uint64_t dups = 0;
#pragma omp parallel for reduction(max : max_load) reduction(+ : dups)
    for (long k = 0; k < (long)pp.b; ++k) {
        auto& v = bins[k];
        sort(v.begin(), v.end());
        size_t before = v.size();
        v.erase(unique(v.begin(), v.end()), v.end());
        dups += before - v.size();
        max_load = max(max_load, v.size());
    }
    m.num("t_hash_ms", sw.ms());
    m.integer("max_bin_load", max_load);
    m.integer("duplicate_entries_removed", dups);
    if (max_load > pp.mu) {
        throw ProtocolFailure("server bin overflow: max load " + to_string(max_load) + " > mu " + to_string(pp.mu));
    }

    // ---- offline 2: crypto context, constants, (optionally) all server plaintexts
    sw.reset();
    EncryptionParameters parms = make_enc_params(pp);
    SEALContext context(parms);
    Evaluator evaluator(context);
    BatchEncoder encoder(context);
    const uint64_t t = parms.plain_modulus().value();
    CWCode cw;
    cw.init(pp.ell, pp.hw);

    uint64_t fact = 1;
    for (uint64_t i = 2; i <= pp.hw; ++i) fact = (u128)fact * i % t;
    vector<Plaintext> sub_pt(pp.hw);  // sub_pt[k] = constant k, k = 1..hw-1
    for (uint64_t k = 1; k < pp.hw; ++k) encoder.encode(vector<uint64_t>(pp.N, k), sub_pt[k]);
    Plaintext inv_fact_pt;  // 1/hw! so that an exact match yields 1 (paper, Algorithm 1)
    encoder.encode(vector<uint64_t>(pp.N, mod_pow(fact, t - 2, t)), inv_fact_pt);

    // The paper's Algorithm 1 divides by hw! on the server so a match is exactly 1. That multiplication by a
    // large constant costs noise; by default the client applies the (public) factor after decryption instead.
    const bool server_scale = a.u64("server-scale", 0) != 0;
    m.integer("server_scale", server_scale);
    const size_t cells = (size_t)pp.mu * pp.gamma;
    double pt_bytes = (double)cells * pp.ell * pp.N * 8.0;
    string pre_arg = a.get("precompute", "auto");
    bool precompute = pre_arg == "1" || (pre_arg == "auto" && pt_bytes <= 6e9);
    m.integer("precompute_plaintexts", precompute);
    m.num("plaintext_table_gb", pt_bytes / 1e9);

    auto build_cell = [&](size_t i, size_t j, vector<Plaintext>& out, vector<char>& nz) {
        vector<vector<uint64_t>> ops(pp.ell, vector<uint64_t>(pp.N, 0));
        vector<uint8_t> bits(pp.ell);
        for (uint64_t k = 0; k < pp.N; ++k) {
            const auto& bin = bins[j * pp.N + k];
            if (i < bin.size()) {
                cw.encode(bin[i], bits.data());
                for (uint64_t l = 0; l < pp.ell; ++l) ops[l][k] = bits[l];
            }
        }
        for (uint64_t l = 0; l < pp.ell; ++l) {
            nz[l] = any_of(ops[l].begin(), ops[l].end(), [](uint64_t x) { return x != 0; });
            if (nz[l]) encoder.encode(ops[l], out[l]);
        }
    };

    vector<Plaintext> pts;
    vector<char> pts_nz;
    if (precompute) {
        pts.resize(cells * pp.ell);
        pts_nz.assign(cells * pp.ell, 0);
#pragma omp parallel for collapse(2) schedule(dynamic)
        for (long i = 0; i < (long)pp.mu; ++i) {
            for (long j = 0; j < (long)pp.gamma; ++j) {
                size_t base = ((size_t)i * pp.gamma + j) * pp.ell;
                vector<Plaintext> out(pp.ell);
                vector<char> nz(pp.ell);
                build_cell(i, j, out, nz);
                for (uint64_t l = 0; l < pp.ell; ++l) {
                    pts_nz[base + l] = nz[l];
                    if (nz[l]) pts[base + l] = std::move(out[l]);
                }
            }
        }
    }
    m.num("t_encode_ms", sw.ms());
    m.num("offline_total_ms", total.ms());

    // ---- online: listen, receive, compute, answer
    int lfd = listen_on((uint16_t)a.u64("port", 1212));
    cout << "LISTENING " << a.u64("port", 1212) << endl;
    int fd = accept_one(lfd);
    Stopwatch online;

    sw.reset();
    string hello = recv_blob(fd);
    if (hello.size() != 16) throw runtime_error("bad hello");
    uint64_t their_fp, client_m;
    memcpy(&their_fp, hello.data(), 8);
    memcpy(&client_m, hello.data() + 8, 8);
    if (their_fp != pp.fingerprint) throw ProtocolFailure("parameter fingerprint mismatch (client and server derived different parameters)");
    string rlk_blob = recv_blob(fd);
    string query_blob = recv_blob(fd);
    m.num("t_recv_ms", sw.ms());
    m.integer("client_set_size", client_m);

    sw.reset();
    RelinKeys rlk;
    {
        stringstream ss(rlk_blob);
        rlk.load(context, ss);
    }
    vector<Ciphertext> inputs(pp.gamma * pp.ell);
    {
        stringstream ss(query_blob);
        for (auto& ct : inputs) ct.load(context, ss);
    }
    m.num("t_deserialize_ms", sw.ms());

    sw.reset();
    vector<Ciphertext> gacc(pp.gamma);
    vector<char> ghas(pp.gamma, 0);
#pragma omp parallel
    {
        vector<Ciphertext> acc(pp.gamma);
        vector<char> has(pp.gamma, 0);
#pragma omp for collapse(2) schedule(dynamic)
        for (long i = 0; i < (long)pp.mu; ++i) {
            for (long j = 0; j < (long)pp.gamma; ++j) {
                vector<Plaintext> local_pts;
                vector<char> local_nz;
                const Plaintext* P;
                const char* NZ;
                if (precompute) {
                    size_t base = ((size_t)i * pp.gamma + j) * pp.ell;
                    P = &pts[base];
                    NZ = &pts_nz[base];
                } else {
                    local_pts.resize(pp.ell);
                    local_nz.assign(pp.ell, 0);
                    build_cell(i, j, local_pts, local_nz);
                    P = local_pts.data();
                    NZ = local_nz.data();
                }
                // h' = sum_l (query bit l) * (server bit l), per bin slot
                Ciphertext sum, prod;
                bool first = true;
                for (uint64_t l = 0; l < pp.ell; ++l) {
                    if (!NZ[l]) continue;
                    evaluator.multiply_plain(inputs[j * pp.ell + l], P[l], prod);
                    if (first) {
                        sum = prod;
                        first = false;
                    } else {
                        evaluator.add_inplace(sum, prod);
                    }
                }
                if (first) continue;  // no real entries in this cell for any bin
                // e = prod_{k=0}^{hw-1} (h' - k) / hw!   (zero unless h' == hw, i.e. equal codewords)
                vector<Ciphertext> operands;
                operands.push_back(sum);
                for (uint64_t k = 1; k < pp.hw; ++k) {
                    Ciphertext c;
                    evaluator.sub_plain(sum, sub_pt[k], c);
                    operands.push_back(std::move(c));
                }
                Ciphertext ind;
                evaluator.multiply_many(operands, rlk, ind);
                for (uint64_t k = 1; k < pp.hw; k *= 2) evaluator.mod_switch_to_next_inplace(ind);
                if (server_scale) evaluator.multiply_plain_inplace(ind, inv_fact_pt);
                if (!has[j]) {
                    acc[j] = std::move(ind);
                    has[j] = 1;
                } else {
                    evaluator.add_inplace(acc[j], ind);
                }
            }
        }
#pragma omp critical
        {
            for (uint64_t j = 0; j < pp.gamma; ++j) {
                if (!has[j]) continue;
                if (!ghas[j]) {
                    gacc[j] = std::move(acc[j]);
                    ghas[j] = 1;
                } else {
                    evaluator.add_inplace(gacc[j], acc[j]);
                }
            }
        }
    }
    auto last_id = context.last_context_data()->parms_id();
    for (uint64_t j = 0; j < pp.gamma; ++j)
        if (ghas[j] && gacc[j].parms_id() != last_id) evaluator.mod_switch_to_inplace(gacc[j], last_id);
    m.num("t_compute_ms", sw.ms());

    sw.reset();
    stringstream resp;
    string flags(pp.gamma, '0');
    for (uint64_t j = 0; j < pp.gamma; ++j) flags[j] = ghas[j] ? '1' : '0';
    for (uint64_t j = 0; j < pp.gamma; ++j)
        if (ghas[j]) gacc[j].save(resp);
    string payload = flags + resp.str();
    send_blob(fd, payload);
    m.num("t_send_ms", sw.ms());
    m.num("online_ms", online.ms());
    m.num("total_ms", total.ms());
    m.integer("bytes_sent", g_bytes_sent);
    m.integer("bytes_received", g_bytes_recv);
    m.integer("response_payload_bytes", payload.size());
    m.integer("request_payload_bytes", query_blob.size() + rlk_blob.size());
    ::close(fd);
    ::close(lfd);
    emit("PSI_METRICS", m.json());
    return 0;
}

// ===================================================================== client
static int run_client(const Args& a) {
    PublicParams pp = make_pp(a);
    omp_set_num_threads((int)a.u64("threads", 1));
    emit("PSI_PARAMS", pp.json());
    MetricsOut m;
    m.str("role", "client");
    Stopwatch total, sw;

    vector<Item> items = read_items(a.require("in"));
    m.num("t_load_ms", sw.ms());
    if (items.size() > pp.cmax) throw invalid_argument("client set (" + to_string(items.size()) + ") larger than --cmax " + to_string(pp.cmax));
    m.integer("client_set_size", items.size());

    // ---- keys
    sw.reset();
    EncryptionParameters parms = make_enc_params(pp);
    SEALContext context(parms);
    KeyGenerator keygen(context);
    SecretKey sk = keygen.secret_key();
    Encryptor encryptor(context, sk);
    Decryptor decryptor(context, sk);
    BatchEncoder encoder(context);
    string rlk_blob;
    {
        stringstream ss;
        keygen.create_relin_keys().save(ss);
        rlk_blob = ss.str();
    }
    m.num("t_keygen_ms", sw.ms());

    // ---- cuckoo hashing, 3 hash functions, no stash
    sw.reset();
    const size_t mm = items.size();
    vector<Placement> pl(mm);
    for (size_t id = 0; id < mm; ++id) pl[id] = split_value(map_element(items[id].x, pp), pp);
    vector<int64_t> table(pp.b, -1);
    vector<uint8_t> widx(pp.b, 0);
    mt19937_64 rng(pp.seed);
    const int kMaxIter = 2000;
    for (size_t id = 0; id < mm; ++id) {
        size_t cur = id;
        int last = -1;
        bool placed = false;
        for (int iter = 0; iter < kMaxIter && !placed; ++iter) {
            for (int h = 0; h < 3; ++h) {
                uint64_t pos = position(pl[cur], h, pp);
                if (table[pos] < 0) {
                    table[pos] = (int64_t)cur;
                    widx[pos] = (uint8_t)h;
                    placed = true;
                    break;
                }
            }
            if (placed) break;
            int h = (int)(rng() % 3);
            if (h == last) h = (h + 1 + (int)(rng() % 2)) % 3;
            uint64_t pos = position(pl[cur], h, pp);
            size_t evicted = (size_t)table[pos];
            int evicted_h = widx[pos];
            table[pos] = (int64_t)cur;
            widx[pos] = (uint8_t)h;
            cur = evicted;
            last = evicted_h;
        }
        if (!placed) throw ProtocolFailure("cuckoo hashing failed (no stash in PEPSI); retry with another --seed on both sides");
    }
    m.num("t_cuckoo_ms", sw.ms());

    // ---- encode: for every bit l of the code, one plaintext whose slot k is bit l of bin k's codeword
    sw.reset();
    CWCode cw;
    cw.init(pp.ell, pp.hw);
    vector<Plaintext> qpts(pp.gamma * pp.ell);
    {
        vector<uint8_t> bits(pp.ell);
        for (uint64_t j = 0; j < pp.gamma; ++j) {
            vector<vector<uint64_t>> ops(pp.ell, vector<uint64_t>(pp.N, 0));
            for (uint64_t k = 0; k < pp.N; ++k) {
                int64_t it = table[j * pp.N + k];
                if (it < 0) continue;  // dummy: all-zero codeword
                cw.encode(stored_value(pl[it], widx[j * pp.N + k], pp), bits.data());
                for (uint64_t l = 0; l < pp.ell; ++l) ops[l][k] = bits[l];
            }
            for (uint64_t l = 0; l < pp.ell; ++l) encoder.encode(ops[l], qpts[j * pp.ell + l]);
        }
    }
    m.num("t_encode_ms", sw.ms());

    sw.reset();
    string query_blob;
    {
        stringstream ss;
        for (auto& pt : qpts) encryptor.encrypt_symmetric(pt).save(ss);
        query_blob = ss.str();
    }
    m.num("t_encrypt_ms", sw.ms());
    m.num("client_prep_total_ms", total.ms());

    // ---- online
    sw.reset();
    int fd = connect_to(a.get("host", "127.0.0.1"), (uint16_t)a.u64("port", 1212));
    m.num("t_connect_ms", sw.ms());

    Stopwatch online;
    sw.reset();
    string hello(16, '\0');
    uint64_t mm64 = mm;
    memcpy(&hello[0], &pp.fingerprint, 8);
    memcpy(&hello[8], &mm64, 8);
    send_blob(fd, hello);
    send_blob(fd, rlk_blob);
    send_blob(fd, query_blob);
    m.num("t_send_ms", sw.ms());

    sw.reset();
    string payload = recv_blob(fd);  // waits for the server's computation
    m.num("t_wait_response_ms", sw.ms());
    ::close(fd);

    // ---- decrypt and decode
    sw.reset();
    if (payload.size() < pp.gamma) throw runtime_error("short response");
    string flags = payload.substr(0, pp.gamma);
    stringstream rs(payload.substr(pp.gamma));
    vector<string> matched;
    uint64_t spurious_empty = 0, not_one = 0;
    const uint64_t t = parms.plain_modulus().value();
    uint64_t fact = 1;
    for (uint64_t i = 2; i <= pp.hw; ++i) fact = (u128)fact * i % t;
    const uint64_t inv_fact = mod_pow(fact, t - 2, t);
    const bool server_scale = a.u64("server-scale", 0) != 0;
    int min_budget = 1 << 30;
    vector<vector<uint64_t>> slots(pp.gamma);
    for (uint64_t j = 0; j < pp.gamma; ++j) {
        if (flags[j] != '1') continue;
        Ciphertext ct;
        ct.load(context, rs);
        min_budget = min(min_budget, decryptor.invariant_noise_budget(ct));
        Plaintext pt;
        decryptor.decrypt(ct, pt);
        encoder.decode(pt, slots[j]);
    }
    m.num("t_decrypt_ms", sw.ms());

    sw.reset();
    for (uint64_t j = 0; j < pp.gamma; ++j) {
        if (slots[j].empty()) continue;
        for (uint64_t k = 0; k < pp.N; ++k) {
            if (slots[j][k] == 0) continue;
            uint64_t val = server_scale ? slots[j][k] : (u128)slots[j][k] * inv_fact % t;  // = number of matching server entries
            if (val != 1) ++not_one;
            int64_t it = table[j * pp.N + k];
            if (it < 0) ++spurious_empty;
            else matched.push_back(items[it].text);
        }
    }
    {
        ofstream out(a.get("out", "result.csv"));
        for (auto& s : matched) out << s << "\n";
    }
    m.num("t_extract_ms", sw.ms());
    m.num("online_ms", online.ms());
    m.num("total_ms", total.ms());
    m.integer("intersection_size", matched.size());
    m.integer("spurious_empty_bin_hits", spurious_empty);
    m.integer("hits_with_value_not_one", not_one);
    m.integer("min_noise_budget_bits", min_budget == (1 << 30) ? 0 : (uint64_t)min_budget);
    m.integer("bytes_sent", g_bytes_sent);
    m.integer("bytes_received", g_bytes_recv);
    m.integer("request_payload_bytes", query_blob.size() + rlk_blob.size());
    m.integer("relin_key_bytes", rlk_blob.size());
    m.integer("query_bytes", query_blob.size());
    m.integer("response_payload_bytes", payload.size());
    emit("PSI_METRICS", m.json());
    return 0;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        cerr << kUsage;
        return 2;
    }
    string mode = argv[1];
    try {
        Args a(argc, argv, 2);
        if (mode == "server") return run_server(a);
        if (mode == "client") return run_client(a);
        cerr << kUsage;
        return 2;
    } catch (const ProtocolFailure& e) {
        cerr << "PROTOCOL FAILURE: " << e.what() << endl;
        return 4;
    } catch (const exception& e) {
        cerr << "ERROR: " << e.what() << endl;
        return 3;
    }
}
