// SPDX-License-Identifier: MIT OR Apache-2.0
// SPDX-FileCopyrightText: 2026 Howard M. Harte
// Generic driver for self-contained --timing SystemVerilog testbenches.

#include "verilated.h"
#include VTOP_H
#if VM_COVERAGE
#include "verilated_cov.h"
#include <string>
#endif

double sc_time_stamp() { return 0; }

int main(int argc, char** argv) {
    auto* context = new VerilatedContext;
    context->commandArgs(argc, argv);
    auto* top = new VTOP_CLASS{context};
    top->eval();
    while (!context->gotFinish() && top->eventsPending()) {
        context->time(top->nextTimeSlot());
        top->eval();
    }
    top->final();
#if VM_COVERAGE
    std::string coverage_file = "coverage.dat";
    const std::string prefix = "+verilator+coverage+file+";
    for (int i = 1; i < argc; ++i) {
        const std::string argument{argv[i]};
        if (argument.rfind(prefix, 0) == 0) coverage_file = argument.substr(prefix.size());
    }
    context->coveragep()->write(coverage_file.c_str());
#endif
    delete top;
    delete context;
    return 0;
}
