// Minimal blocking TCP helpers with length-prefixed messages and byte counters.
#pragma once

#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <thread>

inline uint64_t g_bytes_sent = 0, g_bytes_recv = 0;

inline void send_all(int fd, const void* p, size_t n) {
    const char* c = (const char*)p;
    while (n) {
        ssize_t k = ::send(fd, c, n, MSG_NOSIGNAL);
        if (k <= 0) throw std::runtime_error("send failed: " + std::string(std::strerror(errno)));
        c += k;
        n -= (size_t)k;
        g_bytes_sent += (uint64_t)k;
    }
}

inline void recv_all(int fd, void* p, size_t n) {
    char* c = (char*)p;
    while (n) {
        ssize_t k = ::recv(fd, c, n, 0);
        if (k == 0) throw std::runtime_error("connection closed by peer");
        if (k < 0) throw std::runtime_error("recv failed: " + std::string(std::strerror(errno)));
        c += k;
        n -= (size_t)k;
        g_bytes_recv += (uint64_t)k;
    }
}

inline void send_blob(int fd, const std::string& s) {
    uint64_t len = s.size();
    send_all(fd, &len, sizeof len);
    send_all(fd, s.data(), s.size());
}

inline std::string recv_blob(int fd) {
    uint64_t len = 0;
    recv_all(fd, &len, sizeof len);
    if (len > (1ULL << 36)) throw std::runtime_error("message too large");
    std::string s(len, '\0');
    recv_all(fd, &s[0], len);
    return s;
}

inline int listen_on(uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);
    if (::bind(fd, (sockaddr*)&addr, sizeof addr) != 0) throw std::runtime_error("bind failed: " + std::string(std::strerror(errno)));
    if (::listen(fd, 1) != 0) throw std::runtime_error("listen failed");
    return fd;
}

inline int accept_one(int lfd) {
    int fd = ::accept(lfd, nullptr, nullptr);
    if (fd < 0) throw std::runtime_error("accept failed");
    int one = 1;
    ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    return fd;
}

inline int connect_to(const std::string& host, uint16_t port, int timeout_ms = 30000) {
    auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    while (true) {
        addrinfo hints{}, *res = nullptr;
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_STREAM;
        if (::getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &res) == 0 && res) {
            int fd = ::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
            if (::connect(fd, res->ai_addr, res->ai_addrlen) == 0) {
                ::freeaddrinfo(res);
                int one = 1;
                ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
                return fd;
            }
            ::close(fd);
            ::freeaddrinfo(res);
        }
        if (std::chrono::steady_clock::now() > deadline) throw std::runtime_error("cannot connect to " + host);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
}
