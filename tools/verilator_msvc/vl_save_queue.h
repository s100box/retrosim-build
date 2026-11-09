// SPDX-License-Identifier: MIT OR Apache-2.0
// SPDX-FileCopyrightText: 2026 Howard M. Harte
//
// vl_save_queue.h -- VerilatedSave / VerilatedRestore for SystemVerilog
// queues (VlQueue), which Verilator's --savable does not serialize. Forced
// into every translation unit of a --savable build (verilator_msvc.py
// --force-include), ahead of the code Verilator generates.
#pragma once
#include "verilated.h"
#include "verilated_save.h"

template <typename T_Value, size_t N_MaxSize>
inline VerilatedSerialize& operator<<(VerilatedSerialize& os, const VlQueue<T_Value, N_MaxSize>& rhs) {
    const uint32_t n = static_cast<uint32_t>(rhs.size());
    os << n;
    for (uint32_t i = 0; i < n; ++i) {
        T_Value v = rhs.at(static_cast<int32_t>(i));
        os << v;
    }
    return os;
}

template <typename T_Value, size_t N_MaxSize>
inline VerilatedDeserialize& operator>>(VerilatedDeserialize& os, VlQueue<T_Value, N_MaxSize>& rhs) {
    uint32_t n = 0;
    os >> n;
    rhs.clear();
    for (uint32_t i = 0; i < n; ++i) {
        T_Value v{};
        os >> v;
        rhs.push_back(v);
    }
    return os;
}
