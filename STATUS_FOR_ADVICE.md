# `semantic-toponav` 現状サマリ (GPT pro 先生への相談用)

最終更新: 2026-05-15 (post-PR #59)

---

## 1. プロジェクト概要

OSS の Python パッケージ + ROS2 アダプタスケルトン。
ロボットナビゲーションにおける **Semantic Topological Map** という抽象層を、
dense metric map / HD map と低レベル motion executor (Nav2 / Autoware / MPPI / learned policies) の
**間** の global / semantic / graph-level の planning レイヤとして提供する。

- repo: <https://github.com/rsasaki0109/robot-escape-room> (PyPI package name remains `semantic-toponav`)
- language: Python 3.10+ (core)、C++ なし
- CI: GitHub Actions (pytest matrix py3.10/3.11/3.12 + ruff)
- 規模: **約 16,000 LOC** (`semantic_toponav/` 以下、テスト含む)、**59 PR merged**
- License: Apache-2.0

### Layer の切り方

| Layer | Responsibility | Owned by |
|------|---------------|-----------|
| Global semantic-topological planning | *where* / *why* / *who first* | this repo |
| Local motion execution | *how to move locally* | Nav2 / MPPI / policy |

意図的に含めていないもの: low-level control (MPC, MPPI)、obstacle avoidance、SLAM、
dense occupancy planning、behavior trees。

---

## 2. モジュール構成

```
semantic_toponav/
├── graph/             # TopologyGraph + types + YAML/JSON serialization
├── planner/           # Dijkstra / A* / cost-function 合成 / reservations / time_aware
│                      #   + preference_aware (soft 嗜好) / floor_aware
├── waypoint/          # path → semantic waypoint 列 / describe-path / llm_describe
│                      #   (mid-traversal rewrite 対応)
├── query/             # resolve_goal (NL → node) / llm_resolve / clarification dialog
│                      #   (multi-turn DialogSession)
├── memory/            # 訪問履歴メモリ + embedding-based 場所検索
├── encoders/          # VLM/CLIP プラガブル Backend + AlignedRgbSource plug point
├── llm/               # LLMBackend Protocol (Echo / Anthropic, lazy)
├── conversion/        # occupancy → topology / trajectory → topology / VLM 領域埋め込み
├── coordination/      # SharedScheduler + plan_fleet / _joint / _bnb / _exhaustive
│                      #   + plan_fleet_insert (insertion 修復) + RPC shim + HTTP transport
│                      #   + persistence (save/load) + fairness objectives
├── eval/              # synthetic eval suite (chain / star / doorway / grid 生成器
│                      #   + latency p50/p95 + Jain fairness + JSONL/MD レポート)
├── testing/           # conformance/ 各 Protocol の run_*_conformance 公開ヘルパ
├── visualization/     # pyvis HTML viewer / live-viewer / matplotlib
└── cli/               # argparse + 各サブコマンド (`semantic-toponav` エントリポイント)
```

ROS2 アダプタ: 別パッケージ `semantic_toponav_msgs` (custom msgs) +
`nav2_demo_node` (`SemanticWaypointArray` → `NavigateThroughPoses` ブリッジ)。

---

## 3. PR #35 以降の Shipped 機能 (新しい順)

PR #35 (joint fleet) 直後に GPT pro 先生から
"eval-first → coordination depth → LLM/VLM" の順で組み立てる助言を受け、
ほぼその通りに 25 PR を ship した。

### 評価基盤 (eval-first)
- **PR #36**: Synthetic eval suite — `eval-synthetic` / `eval-report`、4 種生成器
  (chain / star / doorway / multi_floor_office)、latency p50/p95、Jain fairness、JSONL+MD レポート
- **PR #45**: Exhaustive MIS baseline (`plan_fleet_exhaustive`) — 2^n MIS 列挙、
  fixed-paths での grant 上限。BnB が optimum を当てているかの検証用
- **PR #46**: Exhaustive を eval suite に統合 + grant_rate 分母の修正
- **PR #47**: `--bnb-objective` CLI フラグを eval-synthetic に追加

### Coordination depth
- **PR #37**: Hard deadline admission (`admission="hard"`、構造化 `reason_code`)
- **PR #38**: Branch-and-bound joint scheduler (`plan_fleet_bnb`、grants/cost/budget pruning、
  `ConflictExplanation` CBS-lite)
- **PR #41**: Real-time scheduler RPC shim (`SchedulerProtocol` / `Transport` /
  `SchedulerService` / `SchedulerClient` / `LocalTransport`)
- **PR #42**: BnB fairness-aware objectives (`objective="minimax_cost"` / `"max_fairness"`、
  `BnBPlanResult.per_agent_costs`)
- **PR #43**: HTTP reference transport (`HttpSchedulerServer` + `HttpTransport`、stdlib のみ)
- **PR #50**: Scheduler state persistence (`save_scheduler` / `load_scheduler` 既存 YAML/JSON 形式)
- **PR #59**: Insertion-based fleet repair (`plan_fleet_insert`) —
  committed ordering に new request を greedy 挿入。`O(k·(n+k))` で `BnBPlanResult` drop-in

### LLM 軸
- **PR #39**: Region embeddings を LLM prompt context に注入 (`query_encoder=` kwarg、
  scalar `embedding_score=` フィールド注入、raw vector は決して渡さない)
- **PR #40**: Clarification dialog primitives (`ClarificationQuestion` /
  `ClarificationAnswer` / `AmbiguousGoalError` / `clarification=` kwarg)
- **PR #44**: Multi-turn `DialogSession` — 複数 reply にまたがる `free_text` hint 蓄積
  (`start` / `reply` / `is_resolved` / `chosen` / `question`)
- **PR #57**: Mid-traversal LLM describer rewrite (`llm_describe_path` に `start_index=` /
  `situation=` 追加、step 番号は元プランのまま保持)

### VLM 軸
- **PR #52**: Aligned-RGB plug point (`AlignedRgbSource` Protocol + `StaticImageRgbSource`、
  `embed_region_patches` の `rgb_source=` kwarg)。
  Mast3R / RGB-D / orthorectified-camera adapter は別パッケージ実装で良い設計

### Cost / preference
- **PR #54**: Calendar-aware temporal graphs — `time_aware` の `at_date=` kwarg、
  `closed_during` 3-elem 形式 (weekdays フィルタ)、`closed_on_dates` プロパティ。
  weekday-filtered entry を `at_date` なしで見たら raise (silent skip より explicit error)
- **PR #55**: Soft preference cost (`preference_aware(graph, preferences={key: weight})`)
  — 1 つの汎用 blender で caller-defined keys (`scenic` / `crowded` / etc.)。
  `clamp(1.0 - Σ(weight × score), 0.1, 10.0)` で full-zero は防ぐ
- **PR #56**: Node-level preference defaults — `preference_aware` が node にも reach、
  edge が key を持たないとき endpoint nodes の平均を継承 (untagged は "no opinion" として skip)。
  `use_node_defaults=False` で opt-out

### Protocol 健全性
- **PR #53**: Public Protocol conformance suites —
  `semantic_toponav.testing.conformance` に `run_<name>_conformance` を 6 種公開
  (`LLMBackend` / encoder `Backend` / `AlignedRgbSource` / `SchedulerProtocol` /
  `Transport` / `ConflictPolicy`)。adapter 著者は tests または runtime self-check で使える
- **PR #58**: Conformance depth — 既存 6 suite に failure-mode 検査を追加
  (LLMBackend: empty / 8KB / unicode prompts; encoder: opt-in determinism, `cos(v,v)≈1`,
  `embed_text("")`, length-1 batch; ConflictPolicy: no duplicate preempted, scheduler-read-only;
  SchedulerProtocol: idempotent release, mixed-batch atomic rollback, half-open adjacency,
  `conflicts(unknown_resource)=[]`; Transport: release round-trip, repeatable ping;
  AlignedRgbSource: shape stable)

### ドキュメント / branding
- **PR #48**: README slim (1125 → 161 lines) + visual gallery + 5 新 docs/ 投入
  (conversion / cost_composition / coordination / queries / cli)
- **PR #49**: README hero animated GIF (4-frame multi-floor demo) + `examples/build_demo_gif.py`
- **PR #51**: docs/experiments.md を PR #42–#50 で同期
- (PR #53–#56 / #58 / #59 でも各 doc を逐次更新)

---

## 4. 設計上の不変条件 (引き続き堅持されているもの)

- **Protocol-based plugin points**: `LLMBackend` / encoder `Backend` / `ConflictPolicy` /
  `SchedulerProtocol` / `Transport` / `AlignedRgbSource`。Bar は (1) 2 実装以上 OR
  重い optional dep の隔離、(2) core 動作はそれなしで成立、(3) conformance test 完備、
  (4) input/output が小さく domain internals を漏らさない、(5) fallback 定義あり
- **Optional deps via extras**: `[viz]` (pyvis / matplotlib) / `[map]` (scipy / yaml) /
  `[vlm]` (transformers) / `[llm]` (anthropic)。core は zero hard deps
- **Lazy import**: 重い lib (transformers / anthropic) は実 backend を使うときだけ import
- **Deterministic floor + LLM safety layer**: LLM は deterministic 結果を rewrite するだけで
  捏造 (invent steps / invent node ids) できない。Parse 失敗時は silent fallback
- **Cost function composition**: `compose_costs(a, b, c)` で `avoid_restricted` /
  `prefer_elevator` / `reservation_aware` / `time_aware` / `preference_aware` などを自由に stack
- **Frozen dataclasses everywhere**: `Reservation`, `ClaimRequest`, etc.
- **Atomic claim_many with rollback**: 部分 grant が live state を半端な状態にしない
  (conformance suite で明示検証済み)
- **Half-open intervals**: `[09:00, 09:30)` と `[09:30, 10:00)` は overlap せず
  (conformance suite で明示検証済み)

---

## 5. CLI サブコマンド一覧

```
semantic-toponav inspect / add-node / add-edge / rm-node / rm-edge / undo / diff
semantic-toponav from-occupancy / mark-doors / annotate-regions / compact
semantic-toponav embed-regions
semantic-toponav viewer / live-viewer
semantic-toponav plan / waypoints
semantic-toponav describe-path / resolve
semantic-toponav fleet-plan
semantic-toponav eval-synthetic / eval-report
semantic-toponav memory-*
```

共通フラグ抜粋: `--at-time HH:MM` / `--at-date YYYY-MM-DD` / `--reservations FILE` /
`--llm-backend echo|anthropic` / `--strategy {greedy,priority,deadline,joint,bnb,exhaustive}` /
`--bnb-objective {min_cost,minimax_cost,max_fairness}` / `--policy fcfs|priority` /
`--block-edge` / `--block-edge-type` / `--prefer KEY[:WEIGHT]` / `--prefer-floor N` /
`--same-floor-only`

`plan_fleet_insert` (PR #59) は API のみで CLI 未露出。

---

## 6. 残っている open ends

`docs/experiments.md` "Future directions" + memory `project_roadmap_post_pr35.md` から。

### In-repo 候補 (自走可)

| 候補 | サイズ | コメント |
|------|--------|----------|
| `plan_fleet_insert` の CLI / eval-synthetic 統合 | 中 | PR #59 の自然な続き。incremental admission を BnB と比較できる measurement が眠っている |
| Eval generator の拡張 (grid / floor contention 強化) | 中 | 既存 4 種 (chain / star / doorway / multi_floor_office) に加え、grid (MAPF 系) または semantic-toponav 寄りの floor-contention generator を増やすと eval 表現幅が広がる |
| Schedule 可視化 (Gantt 風 `schedule-plot`) | 小〜中 | reservation table が YAML/JSON でしか見えない。time × resource matrix のテキスト or matplotlib 可視化 |
| BnB-based deeper repair (committed prefix も再探索) | 大 | memory で deferred 中。insertion で取りこぼす最適化を拾うが、search が再度 `O((n+k)!)` 寄り |
| DialogSession の persistence (load/save) | 小 | PR #50 と同じ pattern。session を中断 → 再開のユースケース |
| Eval suite に LLM resolve / describer の coverage を追加 | 中 | 今 eval-synthetic は coordination 軸のみ。NL→node の precision/recall が見えない |

### Out-of-repo / user-gate 必要

| 候補 | 状態 |
|------|------|
| **VLM Mast3R adapter package** (`semantic-toponav-mast3r`) | plug point は PR #52 で完備。実装は別 repo (torch / Mast3R weights が重く readable-Python-core を壊す) |
| **Nav2 BT plugin** (C++) | 実用価値は高いが、waypoint / planner result / admission result / reject reason / resolve trace の schema を v1 lock する prerequisite が要る |
| **Web-based graph editor** | OSS UX には良いが research needle を動かさない。Frontend 別 stack |
| **MILP / CP-SAT solver baseline** via `ortools` | 過去 install ブロック歴あり (memory に記録)。opt-in `[opt]` extra で user 承認後 |
| **WebSocket / NATS reference transports** | HTTP は ship 済み。"real user 待ち" で pattern replication 価値が薄い |
| **Cloud-backend conformance** (`AnthropicBackend` / CLIP を実際に通す) | CI に creds 仕込みが要る (user 領域) |
| **Anytime / repair search (BnB-based)** | PR #59 で insertion 版は ship。BnB-based deeper repair は memory で deferred のまま |

### Academic framing target

"Grounded Semantic-Topological Planning for Multi-Robot Navigation under
Language-Specified Goals and Temporal Resource Constraints" —
*middle planning layer* として、LLM/VLM grounding → deterministic planner →
resource-aware fleet scheduler を貫く位置取り。
**主要パーツは全て ship 済み。** 標準 benchmark (MAPF: MovingAI / mapf.info / Flatland、
Habitat HM3D / RxR / OVON) は **材料** であって主戦場ではない (synthetic eval suite が主)。
専用 MAPF solver (CBS / EECBS / MAPF-LNS2) と grid 上で head-to-head しない設計。

---

## 7. GPT pro 先生に聞きたい論点

### 7.1 方向性: 飽和したのか、まだ掘れるのか

PR #35 直後の助言通り eval-first → coordination depth → LLM/VLM の 3 軸を完走した。
**memory 上の roadmap PR #35–#59 は全て shipped**、open ends も上記表に整理済み。

- 今は **maintenance / v1.0 API freeze** を意識して止めるべきタイミングか?
- それとも **次のメジャー方向** (例: physical execution loop の組み込み、
  multi-fleet coordination、environment dynamics の online 学習) を仕込むタイミングか?
- 学術論文化を狙うなら、**今の主要パーツの組み合わせで何を主張すべきか?**

### 7.2 評価の十分性

synthetic eval suite (PR #36 + #45–#47) で latency / grant rate / fairness を回しているが、
specialized MAPF solver (CBS / EECBS / MAPF-LNS2) と直接対決はしていない (意図的)。

- 今の "synthetic / language-aware / time-aware / reservation-aware" 軸で **specialized solver
  が測れない範囲** を測れているか? 何を加えれば論文の評価章として説得力が出るか?
- LLM resolve の precision/recall や describer rewrite の coherence は **未測定** で、
  human-eval / ground-truth corpus を用意するべきか?

### 7.3 Protocol-based plugin の収束

6 Protocol が ship 済み (`LLMBackend` / encoder `Backend` / `ConflictPolicy` /
`SchedulerProtocol` / `Transport` / `AlignedRgbSource`)。Conformance suite (PR #53) +
failure-mode depth (PR #58) で contract は明文化済み。

- これ以上 Protocol を増やすと **premature abstraction** か? 既に増えすぎか?
- 逆に **足りていない** Protocol はあるか?
  (例: graph storage backend、cost-function composition の visitor pattern、etc.)

### 7.4 Out-of-repo 分割の妥当性

memory 方針: torch / heavy weights / C++ / TypeScript は **別 repo / 別 package**。
core は readable Python に集中させる。

- この線引きは引き続き正しいか?
- 例えば Nav2 BT plugin / Foxglove panel / Mast3R adapter のうち、
  **どれを最初に出すと OSS のリーチが伸びる** か?
- もしくは "本体は十分、エコシステム化フェーズに移れ" というシグナルか?

### 7.5 残った in-repo 候補のうち、最大 ROI

§6 の in-repo 候補 6 件のうち、**1 個だけ ship するなら** どれが
academic framing と実用性のどちらにも効くか?

- 個人的には *Eval suite に LLM resolve / describer の coverage を追加* が論文章を厚くしそうだが、
  GPT pro 先生の意見を聞きたい。

---

## 8. アドバイス依頼テンプレ

> 上の現状 (PR #35–#59 完走、roadmap 上の主要 in-tree work は全て ship 済み) を踏まえて、
> 以下のいずれかを優先するべきか意見をください:
>
> (A) **論文化フェーズに移る**: 既存パーツで evaluation chapter を書き、benchmark を整える
> (B) **maintenance / v1.0 freeze**: API stability を強調して practical OSS として伸ばす
> (C) **次のメジャー方向を仕込む**: physical execution loop / online environment learning /
>     multi-fleet coordination のいずれか
> (D) **エコシステム外周** (Nav2 BT plugin / Foxglove panel / Mast3R adapter のどれか) を別 repo で立ち上げる
> (E) **残りの in-repo 候補 (CLI 統合 / eval generator / schedule 可視化 / DialogSession persistence /
>     LLM eval coverage) のうち最大 ROI を 1 つ ship**
> (F) その他 (例: research novelty 狙いで A + C のクロスを)
>
> 加えて、Protocol-based plugin が 6 個になった現状について、
> **次の Protocol を追加するべきか / 止めるべきか** を判断する基準を教えてください。
