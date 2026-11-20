// Shared pieces of the end-to-end PEPSI driver: public parameters, hashing,
// constant-weight encoding, input parsing, metrics output.
//
// Follows the PEPSI paper (USENIX Security 2024):
//  - 3-hash cuckoo hashing on the client (no stash), simple hashing (3 copies) on the server,
//  - permutation-based hashing (PBH) to shorten the stored element to the effective bit length,
//  - perfect constant-weight encoding of the stored values,
//  - lambda = alpha + ceil(log2(b * mu)) for large elements (Lemma 1), mu from the paper's bound.
#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "seal/seal.h"
#include "utils.h"  // upstream: Params (crypto parameter table)

typedef unsigned __int128 u128;

struct ProtocolFailure : std::runtime_error {  // exit code 4: failure the paper allows (bin overflow, cuckoo)
    using std::runtime_error::runtime_error;
};

// ---------------------------------------------------------------- timing / metrics
struct Stopwatch {
    std::chrono::steady_clock::time_point t0 = std::chrono::steady_clock::now();
    void reset() { t0 = std::chrono::steady_clock::now(); }
    double ms() const {
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    }
};

struct MetricsOut {
    std::vector<std::pair<std::string, std::string>> items;
    void num(const std::string& k, double v) {
        char buf[64];
        std::snprintf(buf, sizeof buf, "%.3f", v);
        items.emplace_back(k, buf);
    }
    void integer(const std::string& k, uint64_t v) { items.emplace_back(k, std::to_string(v)); }
    void str(const std::string& k, const std::string& v) { items.emplace_back(k, "\"" + v + "\""); }
    std::string json() const {
        std::string s = "{";
        for (size_t i = 0; i < items.size(); ++i) {
            if (i) s += ",";
            s += "\"" + items[i].first + "\":" + items[i].second;
        }
        return s + "}";
    }
};

// ---------------------------------------------------------------- arguments
struct Args {
    std::map<std::string, std::string> kv;
    Args(int argc, char** argv, int start) {
        for (int i = start; i < argc; i += 2) {
            std::string k = argv[i];
            if (k.rfind("--", 0) != 0 || i + 1 >= argc) throw std::invalid_argument("bad argument: " + k);
            kv[k.substr(2)] = argv[i + 1];
        }
    }
    bool has(const std::string& k) const { return kv.count(k) > 0; }
    std::string get(const std::string& k, const std::string& def = "") const {
        auto it = kv.find(k);
        return it == kv.end() ? def : it->second;
    }
    std::string require(const std::string& k) const {
        if (!has(k)) throw std::invalid_argument("missing --" + k);
        return kv.at(k);
    }
    uint64_t u64(const std::string& k, uint64_t def) const { return has(k) ? std::stoull(kv.at(k)) : def; }
};

// ---------------------------------------------------------------- math helpers
inline uint64_t ceil_log2(u128 x) {  // smallest e with 2^e >= x (x >= 1)
    uint64_t e = 0;
    u128 p = 1;
    while (p < x) {
        p <<= 1;
        ++e;
    }
    return e;
}

inline uint64_t mix64(uint64_t z) {  // splitmix64 finalizer; public, keyed by seeds below
    z += 0x9e3779b97f4a7c15ULL;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

// ---------------------------------------------------------------- constant-weight code
struct CWCode {
    uint64_t ell = 0, hw = 0;
    std::vector<std::vector<uint64_t>> C;  // C[n][k], saturating at 2^63
    void init(uint64_t ell_, uint64_t hw_) {
        ell = ell_;
        hw = hw_;
        const uint64_t CAP = 1ULL << 63;
        C.assign(ell + 1, std::vector<uint64_t>(hw + 1, 0));
        for (uint64_t n = 0; n <= ell; ++n) {
            C[n][0] = 1;
            for (uint64_t k = 1; k <= hw && k <= n; ++k) {
                u128 s = (u128)C[n - 1][k - 1] + (k <= n - 1 ? C[n - 1][k] : 0);
                C[n][k] = s > CAP ? CAP : (uint64_t)s;
            }
        }
    }
    // Colex rank -> codeword (same mapping as upstream get_cw). bits must have size ell.
    void encode(uint64_t value, uint8_t* bits) const {
        std::fill(bits, bits + ell, 0);
        uint64_t rem = value;
        long k = (long)hw;
        for (long p = (long)ell - 1; p >= 0 && k > 0; --p) {
            uint64_t c = C[p][k];
            if (rem >= c) {
                bits[p] = 1;
                rem -= c;
                --k;
            }
        }
    }
};

// ---------------------------------------------------------------- public parameters
// Both parties derive the same parameters from the same public inputs (set sizes, alpha, ...);
// a fingerprint of the result is checked in the handshake.
struct PublicParams {
    // inputs
    uint64_t n = 0;            // server set size (public)
    uint64_t cmax = 4096;      // maximum client set size (public; fixes the number of bins)
    uint64_t alpha = 40;       // statistical failure exponent
    uint64_t lambda_arg = 0;   // 0 = Lemma 1, otherwise fixed element bit length (e.g. 32)
    uint64_t hw = 0;           // Hamming weight, 0 = auto
    bool hash_index = false;   // append the hash-function index to the stored value (see README)
    bool identity_map = false; // use the element itself (must fit in lambda bits) instead of hashing
    uint64_t seed = 0x5eed;

    // derived
    uint64_t log_N = 0, N = 0, gamma = 0, b = 0, mu = 0, lambda = 0, ell = 0, prime_bits = 20;
    u128 M = 0;                 // PBH: element = xH * M + xL, xH < b, xL < M
    uint64_t stored_values = 0; // number of distinct values a bin entry can take
    std::vector<seal::Modulus> coeff_bits;
    uint64_t fingerprint = 0;

    void derive() {
        if (n == 0) throw std::invalid_argument("--n (server set size) must be > 0");
        if (hw == 0) hw = (lambda_arg && lambda_arg <= 40) ? 8 : 16;
        if (hw < 2 || hw > 64) throw std::invalid_argument("--hw must be in [2,64]");
        Params base(Task::PSI, 1, 1, 19, hw, 1);  // crypto table only (poly degree, coeff modulus)
        log_N = base.log_poly_modulus_degree;
        coeff_bits = base.coeff_bits;
        prime_bits = base.prime_bitlength;
        N = 1ULL << log_N;
        gamma = std::max<uint64_t>(1, (uint64_t)std::ceil(1.27 * (double)cmax / (double)N));
        b = N * gamma;
        // server bin-load bound: 3n balls into b bins (same formula as upstream main-psi; reproduces
        // the paper's mu = 526 for n=2^20, b=8192 and mu = 296 for n=2^20, b=16384)
        double balls = 3.0 * (double)n;
        mu = std::max<uint64_t>(1, (uint64_t)std::ceil(balls / (double)b + 2.0 * std::sqrt(balls * std::log2((double)b) / (double)b)));
        lambda = lambda_arg ? lambda_arg : alpha + ceil_log2((u128)b * mu);  // Lemma 1 with client bin load 1
        if (lambda < 8 || lambda > 120) throw std::invalid_argument("element bit length out of range");
        M = (((u128)1 << lambda) + b - 1) / b;
        if (M > ((u128)1 << 62)) throw std::invalid_argument("effective element too long (> 62 bits)");
        stored_values = (uint64_t)M * (hash_index ? 3 : 1);
        ell = hw;
        for (;; ++ell) {  // smallest code length with C(ell, hw) >= number of values
            CWCode tmp;
            tmp.init(ell, hw);
            if (tmp.C[ell][hw] >= stored_values) break;
            if (ell > 4096) throw std::invalid_argument("no code length found");
        }
        std::ostringstream os;
        os << n << "|" << cmax << "|" << alpha << "|" << lambda << "|" << hw << "|" << hash_index << "|" << identity_map << "|"
           << seed << "|" << b << "|" << mu << "|" << ell << "|" << log_N;
        uint64_t h = 1469598103934665603ULL;
        for (unsigned char c : os.str()) h = (h ^ c) * 1099511628211ULL;
        fingerprint = h;
    }

    uint64_t eff_bits() const { return ceil_log2(M); }

    std::string json() const {
        MetricsOut m;
        m.integer("n", n); m.integer("cmax", cmax); m.integer("alpha", alpha); m.integer("hw", hw);
        m.integer("log_N", log_N); m.integer("N", N); m.integer("gamma", gamma); m.integer("bins", b);
        m.integer("mu", mu); m.integer("lambda", lambda); m.integer("effective_bits", eff_bits());
        m.integer("ell", ell); m.integer("hash_index", hash_index); m.integer("identity_map", identity_map);
        m.integer("stored_values", stored_values);
        uint64_t cb = 0;
        for (auto& p : coeff_bits) cb += p.bit_count();
        m.integer("coeff_modulus_bits", cb);
        return m.json();
    }
};

inline PublicParams make_pp(const Args& a) {
    PublicParams pp;
    pp.n = a.u64("n", 0);
    pp.cmax = a.u64("cmax", 4096);
    pp.alpha = a.u64("alpha", 40);
    std::string lam = a.get("lambda", "auto");
    pp.lambda_arg = (lam == "auto") ? 0 : std::stoull(lam);
    pp.hw = a.u64("hw", 0);
    pp.hash_index = a.u64("hash-index", 0) != 0;
    pp.identity_map = a.get("map", "hash") == "identity";
    pp.seed = a.u64("seed", 0x5eed);
    pp.derive();
    return pp;
}

// ---------------------------------------------------------------- elements and hashing
struct Item {
    u128 x;
    std::string text;
};

inline std::vector<Item> read_items(const std::string& path) {
    std::ifstream f(path);
    if (!f) throw std::runtime_error("cannot open " + path);
    std::vector<Item> items;
    std::string line;
    while (std::getline(f, line)) {
        size_t a = line.find_first_not_of(" \t\r\n"), z = line.find_last_not_of(" \t\r\n");
        if (a == std::string::npos) continue;
        std::string t = line.substr(a, z - a + 1);
        if (t.size() > 32) throw std::runtime_error("element longer than 32 hex chars: " + t);
        u128 v = 0;
        for (char c : t) {
            int d = (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
            if (d < 0) throw std::runtime_error("not a hex element: " + t);
            v = (v << 4) | (u128)d;
        }
        items.push_back({v, t});
    }
    return items;
}

// element (128 bit) -> lambda-bit value
inline u128 map_element(u128 x, const PublicParams& pp) {
    u128 mask = ((u128)1 << pp.lambda) - 1;
    if (pp.identity_map) {
        if (x & ~mask) throw std::runtime_error("--map identity: element does not fit in lambda bits");
        return x;
    }
    uint64_t hi = (uint64_t)(x >> 64), lo = (uint64_t)x;
    uint64_t a = mix64(lo ^ mix64(pp.seed ^ 0xA5A5A5A5ULL));
    uint64_t c = mix64(hi ^ a ^ 0x1234567ULL);
    u128 v = ((u128)c << 64) | mix64(a ^ c);
    return v & mask;
}

// permutation-based hashing with hash function i: bin position and stored value
struct Placement {
    uint64_t xh, xl;
};
inline Placement split_value(u128 v, const PublicParams& pp) { return {(uint64_t)(v / pp.M), (uint64_t)(v % pp.M)}; }
inline uint64_t hash_i(uint64_t xl, int i, const PublicParams& pp) {
    return mix64(xl ^ mix64(pp.seed + 0x1000 + (uint64_t)i)) % pp.b;
}
inline uint64_t position(const Placement& p, int i, const PublicParams& pp) { return (p.xh + hash_i(p.xl, i, pp)) % pp.b; }
inline uint64_t stored_value(const Placement& p, int i, const PublicParams& pp) { return pp.hash_index ? p.xl * 3 + (uint64_t)i : p.xl; }

inline uint64_t mod_pow(uint64_t base, uint64_t e, uint64_t mod) {
    u128 r = 1, b = base % mod;
    while (e) {
        if (e & 1) r = r * b % mod;
        b = b * b % mod;
        e >>= 1;
    }
    return (uint64_t)r;
}

inline seal::EncryptionParameters make_enc_params(const PublicParams& pp) {
    seal::EncryptionParameters parms(seal::scheme_type::bfv);
    parms.set_poly_modulus_degree(pp.N);
    parms.set_coeff_modulus(pp.coeff_bits);
    parms.set_plain_modulus(seal::PlainModulus::Batching(pp.N, pp.prime_bits));
    return parms;
}
