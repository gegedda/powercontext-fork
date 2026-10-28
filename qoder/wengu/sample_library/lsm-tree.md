---
title: LSM-Tree：写优化的存储引擎结构
year: 1996
tags: 存储引擎,写优化,LSM
source: O'Neil et al., The Log-Structured Merge-Tree (LSM-Tree), 1996
---

# LSM-Tree：写优化的存储引擎结构

## 定义

LSM-Tree（Log-Structured Merge-Tree，日志结构合并树）由 Patrick O'Neil 等人在 1996 年的论文《The Log-Structured Merge-Tree (LSM-Tree)》中提出。它把随机写转化为顺序写：数据先追加到内存中的 MemTable，同时写 WAL，MemTable 达到阈值后冻结为不可变的 Immutable MemTable，再刷盘成为 SSTable（Sorted String Table）。

## 核心机制

1. **MemTable 与 WAL**：所有写入先进入 MemTable（通常是有序跳表或 B 树），并顺序追加到 WAL。WAL 保证崩溃不丢数据，MemTable 保证写入内存即可返回。
2. **Immutable MemTable 与 Flush**：MemTable 写满后转为只读，由后台线程刷成 SSTable，磁盘上的 SSTable 本身有序。
3. **Compaction（合并）**：后台按策略把多个 SSTable 合并，消除重复键、丢弃墓碑（tombstone）记录。常见策略是 Leveled Compaction（LevelDB/RocksDB 默认）和 Tiered Compaction。Leveled 把第 L 层大小控制在约 10 倍于 L-1 层。
4. **读放大与 Bloom Filter**：一次点查要从 MemTable、Immutable MemTable 和逐层 SSTable 里查找，这就是读放大。Bloom Filter 把不存在的键几乎一次性排除，显著降低读放大。

## 写放大、读放大、空间放大

- **写放大**：同一份数据在 compaction 中被反复重写。Leveled Compaction 写放大通常为每层 10 倍量级，因此高写负载场景常用 Tiered 策略折中。
- **读放大**：查询需要检查多个层级与文件。
- **空间放大**：旧版本数据和墓碑暂时占用空间。

三者互相制约，RocksDB 用 `level0_file_num_compaction_trigger`、`max_bytes_for_level_base` 等参数调整。

## 常见误区

- LSM-Tree 只适合写多场景的说法不准确：通过 Bloom Filter、块缓存和压缩，点查性能可以接近 B+Tree。
- Compaction 不是可选优化，而是正确性相关：墓碑清理依赖合并。
- 事务隔离需要额外机制：LSM 只解决存储布局，MVCC 版本链、锁与快照由上层实现。

## 与 B+Tree 的对比

B+Tree 原地更新，写放大低但随机写多；LSM-Tree 顺序写吞吐高，但需要后台合并成本。OceanBase、RocksDB、LevelDB、HBase、Cassandra 等系统都采用或借鉴了 LSM 思想。
