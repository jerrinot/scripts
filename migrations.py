#!/usr/bin/python
# @lint-avoid-python-3-compatibility-imports
#
# runqlat   Run queue (scheduler) latency as a histogram.
#           For Linux, uses BCC, eBPF.
#
# USAGE: runqlat [-h] [-T] [-m] [-P] [-L] [-p PID] [interval] [count]
#
# This measures the time a task spends waiting on a run queue for a turn
# on-CPU, and shows this time as a histogram. This time should be small, but a
# task may need to wait its turn due to CPU load.
#
# This measures two types of run queue latency:
# 1. The time from a task being enqueued on a run queue to its context switch
#    and execution. This traces ttwu_do_wakeup(), wake_up_new_task() ->
#    finish_task_switch() with either raw tracepoints (if supported) or kprobes
#    and instruments the run queue latency after a voluntary context switch.
# 2. The time from when a task was involuntary context switched and still
#    in the runnable state, to when it next executed. This is instrumented
#    from finish_task_switch() alone.
#
# Copyright 2016 Netflix, Inc.
# Licensed under the Apache License, Version 2.0 (the "License")
#
# 07-Feb-2016   Brendan Gregg   Created this.

from __future__ import print_function
from bcc import BPF
from time import sleep, strftime
import argparse

# arguments
examples = """examples:
    ./runqlat            # summarize run queue latency as a histogram
    ./runqlat 1 10       # print 1 second summaries, 10 times
    ./runqlat -mT 1      # 1s summaries, milliseconds, and timestamps
    ./runqlat -P         # show each PID separately
    ./runqlat -p 185     # trace PID 185 only
"""
parser = argparse.ArgumentParser(
    description="Summarize run queue (scheduler) latency as a histogram",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=examples)
parser.add_argument("-T", "--timestamp", action="store_true",
    help="include timestamp on output")
parser.add_argument("-p", "--pid", help="trace this PID only", required=True)
parser.add_argument("interval", nargs="?", default=99999999,
    help="output interval, in seconds")
parser.add_argument("--ebpf", action="store_true",
    help=argparse.SUPPRESS)
args = parser.parse_args()
debug = 0

# define BPF program
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>
#include <linux/nsproxy.h>
#include <linux/pid_namespace.h>

typedef struct pid_key {
    u64 id;    // work around
    u64 slot;
} pid_key_t;

typedef struct pidns_key {
    u64 id;    // work around
    u64 slot;
} pidns_key_t;

struct data_t {
    u64 cpu;
};

BPF_PERF_OUTPUT(migrations);


struct rq;

// record enqueue timestamp
static int trace_enqueue(u32 tgid, u32 pid)
{
    if (FILTER || pid == 0)
        return 0;
    u64 ts = bpf_ktime_get_ns();
    return 0;
}

RAW_TRACEPOINT_PROBE(sched_wakeup)
{
    // TP_PROTO(struct task_struct *p)
    struct task_struct *p = (struct task_struct *)ctx->args[0];
    return trace_enqueue(p->tgid, p->pid);
}

RAW_TRACEPOINT_PROBE(sched_wakeup_new)
{
    // TP_PROTO(struct task_struct *p)
    struct task_struct *p = (struct task_struct *)ctx->args[0];
    return trace_enqueue(p->tgid, p->pid);
}

RAW_TRACEPOINT_PROBE(sched_switch)
{
    // TP_PROTO(bool preempt, struct task_struct *prev, struct task_struct *next)
    struct task_struct *prev = (struct task_struct *)ctx->args[1];
    struct task_struct *next = (struct task_struct *)ctx->args[2];
    u32 pid, tgid;

    // ivcsw: treat like an enqueue event and store timestamp
    if (prev->state == TASK_RUNNING) {
        tgid = prev->tgid;
        pid = prev->pid;
        if (!(FILTER || pid == 0)) {
            u64 ts = bpf_ktime_get_ns();
            struct data_t data = {};
            data.cpu = prev->cpu;
            migrations.perf_submit(ctx, &data, sizeof(data));
        }
    }


    tgid = next->tgid;
    pid = next->pid;
    if (FILTER || pid == 0)
        return 0;

    uint cpu = next->cpu;
//    struct data_t data = {};
//    data.cpu = cpu;
//    migrations.perf_submit(ctx, &data, sizeof(data));

    return 0;
}
"""


# code substitutions
if args.pid:
    # pid from userspace point of view is thread group from kernel pov
    # bpf_text = bpf_text.replace('FILTER', 'tgid != %s' % args.pid)
    bpf_text = bpf_text.replace('FILTER', 'pid != %s' % args.pid)
else:
    bpf_text = bpf_text.replace('FILTER', '0')



# load BPF program
b = BPF(text=bpf_text)

print("Tracing run queue latency... Hit Ctrl-C to end.")

def print_event(cpu, data, size):
    event = b["migrations"].event(data)
    print(event.cpu)

# output
exiting = 0 if args.interval else 1
b["migrations"].open_perf_buffer(print_event)

while (1):
    b.perf_buffer_poll()
