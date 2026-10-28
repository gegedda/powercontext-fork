---
title: Raft 共识算法
year: 2014
tags: 分布式,共识,Raft
source: Ongaro & Ousterhout, In Search of an Understandable Consensus Algorithm, USENIX ATC 2014
---

# Raft 共识算法

## 定义与出处

Raft 由 Diego Ongaro 和 John Ousterhout 在 2014 年的 USENIX ATC 论文《In Search of an Understandable Consensus Algorithm》中提出，目标是比 Paxos 更容易理解和实现。Raft 把共识拆成三个子问题：Leader 选举、日志复制、安全性。

## Leader 选举

- 节点角色只有三种：Leader、Follower、Candidate。
- 每个节点维护**任期号 term**，term 单调递增；收到更大 term 的消息立即转为 Follower。
- 选举超时（election timeout）通常取 150–300 ms 的随机值，谁先超时谁把 term 加一、投自己一票、向其他节点发 RequestVote。
- 获得**多数派（majority）**选票即成为 Leader；平票则随机等待后重试。

## 日志复制

- 客户端请求先写 Leader 的日志，Leader 并行发给所有 Follower 的 AppendEntries。
- 当日志被**多数派**确认持久化后，Leader 提交（commit）并把结果返回客户端。
- `commitIndex` 之前的日志保证不会丢失；`lastApplied` 表示已应用到状态机的位置。
- **日志匹配特性**：如果两个日志在相同索引处的 term 相同，则它们之前的日志完全一致。

## 安全性约束

- 选举限制：Candidate 的日志必须至少和多数派中任一节点一样新，才能当选。
- 领导者只能提交当前任期的日志条目来间接提交旧任期日志。
- 成员变更使用单节点变更或联合共识（joint consensus）。
- 日志压缩用快照（snapshot）+ InstallSnapshot RPC。

## 与 Paxos 的差异

Raft 显式选举 Leader，日志必须连续；Paxos（Multi-Paxos）允许日志空洞，状态更灵活但实现更复杂。etcd、TiKV、CockroachDB、OceanBase 的 Paxos 变体都属于这一族。
