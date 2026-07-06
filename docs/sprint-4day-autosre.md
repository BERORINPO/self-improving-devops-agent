# AutoSRE — 4-Day Hackathon Sprint Plan

> **Status**: 2026-07-06 再始動（W1 停止から縮退スコープで sprint）
> **締切**: 2026-07-10 (金) 23:59 提出 / 一次審査 7/13-17 / 二次 7/21-24 / 告知 7/30 / 最終発表 8/19
> **イベント**: DevOps × AI Agent Hackathon（主催 Findy / メインスポンサー Google Cloud）
> **提出物 3 点**: 公開 GitHub URL / デプロイ URL / ProtoPedia URL
> **必須要件**: Google Cloud AI 技術 ≥1（Gemini / ADK）＋ Google Cloud プロダクト ≥1（Cloud Run）

## プロダクト：AutoSRE — 自律オンコール・エージェント

壊れた Cloud Run デプロイを、**自分でログを読んで原因特定 → 修正 PR を実際に立てる → 人間承認を待つ → 承認後に直して復旧を自分で確認する**エージェント。全ステップを Ops コンソールにライブ配信（SSE）。

### 5 ステップ（＝審査基準①「自律の必然性」への回答）

| ステップ | 中身 | 単発 LLM で不可能な理由 |
|---|---|---|
| **Sense** | 実 Cloud Run status + 実 Cloud Logging を tool で読む | 中間結果で次手が変わる ReAct ループ |
| **Diagnose** | Gemini が実ログ根拠で「env 欠落」と断定 | 実ログ引用＝grounding（幻覚でない）|
| **Propose** | IaC 差分（env 復元）を生成 | — |
| **Gate** | **人間承認まで一時停止**（信頼境界の中心）| 状態保持したまま中断/再開 |
| **Verify** | 修正後 `/healthz` が 200 になるまで自分で確認 | observe-act-observe 閉ループ |

**一線**: 読む・診断・提案＝自律、merge・deploy＝必ず人間承認（Safe の物語）。

## スコープ（22 → 8 に圧縮）

### 残す（8）
1. ADK+Gemini エージェント核（既存 scaffold を単一 ReAct agent に転用）
2. env 欠落の 1 シナリオ E2E
3. SSE ライブタイムライン
4. Evidence パネル（実 tool 出力）
5. 承認ゲート（人間介入・pause/resume）
6. 実 GitHub PR（永続的な提出証拠）
7. 実サービスへの復旧確認
8. Cloud Run デプロイ

### 捨てる（→ roadmap 送り）
Multi-Agent Debate / Self-Improving ポリシー学習 / Pub/Sub+Monitoring 検知（→ 手動 inject）/ Firestore（→ インメモリ）/ Terraform・setup.sh / GitHub App 2 分割（→ PAT 1 本）/ Agent SLO ダッシュボード / 2 つ目シナリオ / Orchestrator-Worker 分割 / Vercel AI SDK / config.yaml 汎用化

## スタック（最小 compliant）

- **AI**: ADK `google-adk>=1.34.0,<2.0.0` ＋ Gemini 2.5（Vertex AI、Flash=調査 / Pro=診断）
- **Product**: Cloud Run（agent-service + target-service）＋ Cloud Logging ＋ Secret Manager
- **Backend**: Python 3.12 + FastAPI + uvicorn（`get_fast_api_app` or 最小自作）、SSE=StreamingResponse
- **Frontend**: 既存 fork の Next.js 16 studio-admin を **1 枚の Incident ページに削る**（native EventSource）
- **GitHub**: classic PAT（repo scope）を Secret Manager、`open_pull_request` + `merge` を REST で
- **Region**: asia-northeast1
- **Cost**: 無料枠内で $数ドル（$300 クーポン不要）

## 決定事項（2026-07-06 ロック）

1. 参加登録: **済**
2. Gemini backend: **Vertex AI**（Cloud Run から ADC で鍵レス、"旧 Vertex AI"＝必須技術を明示的に満たす）。ローカル開発のみ AI Studio 無料キー可
3. PR 先: **専用デモ用 target repo を新規作成**（提出 repo を汚さない・保護ブランチ merge 事故回避）＋ PAT を Secret Manager
4. 公開: 公開 repo・公開デプロイ URL・ProtoPedia。**ProtoPedia/README は公開前にメイ 9 軸審査**

## 4 日タイムライン

| 日 | やること | 出口ゲート |
|---|---|---|
| **Day1（7/6）** | GCP 再認証 → project → billing link → API 有効化 → target-service と agent-service を Cloud Run に空デプロイ → **実 Gemini 呼び出し 1 回＋実ログ読み 1 回を通す** | 🚦smoke 緑でなければ即再スコープ |
| **Day2（7/7）** | ReAct 核：3-4 tool（status/logs/config/open_PR）＋Gemini 診断＋構造化出力＋障害注入スクリプト。**調査→診断→実 PR 起票まで通す** | 実 PR が立つ |
| **Day3（7/8）** | UI（Incident 1 枚）＋承認ゲート＋復旧確認＋SSE。`--replay` モード＋既知 good run 録画。**Day3 末で機能凍結** | フル E2E 録画取得 |
| **Day4（7/9）** | デモ動画（good run から）＋README＋ProtoPedia。**メイ 9 軸後に公開**。バッファ | 提出物 3 点完成 |
| **7/10** | 最終確認 → **3 URL 提出（23:59 まで）** | 提出完了 |

工数目安 ≈ 30h（agent 6h + infra 2.5h + UI 10h + 統合 4h + 提出物 8h）。UI が最大の時間食い → 遅れたら **FastAPI が返す 1 枚 HTML で deploy URL 要件を満たす**逃げ道。

## Day1 デプロイ手順（agent-service を Cloud Run Service 化）

recon 確定手順（Dockerfile は 8 割完成、HTTP server 追加が必要）:

1. requirements に `fastapi`, `uvicorn[standard]` 追加
2. `packages/agent/src/agents/server.py` を作成（`get_fast_api_app` か最小 FastAPI + ADK Runner、`/healthz` + `/incident` + `/events` SSE）
3. Dockerfile CMD を `uvicorn agents.server:app --host 0.0.0.0 --port ${PORT}` に
4. `gcloud run deploy sida-agent --source packages/agent --region asia-northeast1 --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=...,GOOGLE_CLOUD_LOCATION=asia-northeast1`
5. runtime SA に `roles/aiplatform.user`

## トップリスク（緩和策）

1. **コールドスタート**（何も deploy 済でない）→ Day1 ゲートで潰す。緑にならなければ即再スコープ
2. **Cloud Run で SSE が途中停止**（既知問題）→ ヘッダ対策（no Content-Length / X-Accel-Buffering:no / keepalive）＋ `min-instances=1` ＋ polling fallback。Day2 末で判断
3. **本番デモの脆さ**（Gemini 429 / 再デプロイ 30-60s）→ **録画＋replay モード**が命綱、Day3 までに存在させる
4. **Gemini tool-calling の暴走/JSON 崩れ** → tool 3-4 個・max iteration cap・structured output・retry・決定的 fallback
5. **承認ゲート下の GitHub merge**（保護ブランチで失敗）→ target repo は保護なし、merge ステップ事前テスト
6. **スコープ逆流**（Debate/Self-Improving を最終日に足す誘惑）→ drop_list 凍結、新案は roadmap のみ

## 提出物メモ

- **GitHub**: 提出 repo = `BERORINPO/self-improving-devops-agent`（README がこの物語を反映）
- **デプロイ URL**: ops-console（または hosted replay）
- **ProtoPedia**: Sense/Diagnose/Propose/Gate/Verify を製品として提示、実 merged PR をクリック可能な証拠として埋め込む、before/after 503→200、roadmap で cut 機能を拡張性クレジットに変換

## Day-1 実績（2026-07-06）— 🚦 ゲート通過

GCP 基盤＋2 サービスの Cloud Run デプロイ＋smoke 完了。

- **project**: `bero-devops-agent`（billing linked、無料枠運用）/ region `asia-northeast1`
- **agent-service**（`packages/agent`）: FastAPI + ADK。`/` `/health` `/smoke`。Vertex Gemini（`global`, gemini-2.5-flash）+ Cloud Logging read が **`/smoke` で overall_ok:true**
  - env: `GOOGLE_GENAI_USE_VERTEXAI=TRUE` / `GOOGLE_CLOUD_PROJECT=bero-devops-agent` / `GOOGLE_CLOUD_LOCATION=global`
  - runtime SA に `roles/aiplatform.user` + `roles/logging.viewer`
- **target-service**（`services/target-service`）: `DATABASE_URL` 無しで `/health` 503、有りで 200。`/health` = 200 確認済
- URL は `gcloud run services describe <svc> --region asia-northeast1 --format="value(status.url)"` で取得（PR/README には最終版を記載）

### 潰した Cloud Run の罠（重要・再発防止）
1. **PowerShell の comma 分割**: `--set-env-vars A=1,B=2,C=3` を PowerShell が配列化し gcloud に 1 個しか届かない → `KeyError: GOOGLE_CLOUD_PROJECT`。**フラグ全体をクォート**（`"--update-env-vars=A=1,B=2,C=3"`）で回避
2. **`/healthz` は GFE 予約パス**: Cloud Run のフロントが `/healthz` を横取りして GFE 404 を返し、コンテナに届かない。**health エンドポイントは `/health` を使う**（`/healthz` は使わない）
3. **並行 `--source` デプロイの AR リポジトリ競合**: 初回は 2 本同時に `cloud-run-source-deploy` を作ろうとして `ALREADY_EXISTS`。1 本目成功後は解消（初回だけ直列化すれば安全）
4. **FastAPI の戻り値注釈に `Response` サブクラスの union 禁止**: `-> JSONResponse | dict` はルート登録時に落ちる。注釈を外すか単一 `Response` 型に

## Polish 実績（SSE ライブ配信 + 自己リセット）

- **SSE ライブ配信が Cloud Run で動作**: `/incident/stream`（GET, EventSource）が agent の各ステップを逐次配信。実測でイベントが 8-22s に分散到達（末尾一括バッファなし）。効いたヘッダ: `Cache-Control: no-cache, no-transform` + `X-Accel-Buffering: no`。EventSource 自動再接続は `retry: 60000` + `done` イベントで client 側 close して抑止。
- **自己リセット**: `/reset`（POST）が target を再度 503 に + config repo を壊れた状態に戻す → 審査員が何度でも「検知→修正→復旧」を再現可能。UI に「Reset demo」ボタン。
- **判明した罠**: bodyless POST を curl `-X POST`（body なし）で叩くと GFE が **HTTP 411 (Length Required)** を返す。ブラウザ fetch は Content-Length:0 を自動送信するため UI では問題なし。curl テスト時は `-d ""` で回避。
- **フルサイクル Cloud Run 検証済**: SSE 診断→実PR / `/approve`（merge→run_v2 適用→503→200）/ `/reset`（再武装）全て本番で通過。
