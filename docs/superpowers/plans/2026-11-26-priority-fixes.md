# 優先改善（2026-11-26）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 11/26 の改善案一覧のうち、コードだけで完結し、失敗しても公開を止めない項目をまとめて入れる。

**Architecture:** 判定や文字列づくりは新しい `site/sitekit.py`（他のモジュールを読み込まない純粋な関数）に置き、`site/build.py` はそれを呼ぶだけにする。ビルド結果の点検は `tests/site_smoke.py`（静的）と `tests/site_smoke_js.py`（ブラウザ。手元で実行）に分ける。

**Tech Stack:** Python 3.12（標準ライブラリ + bs4）、pytest、Playwright（手元の確認のみ）。

**Spec:** 改善案一覧の番号 1・9(騎手)・12・18・19・21・23・26・28・29・31・54・61・62。ユーザーの指示は「優先すべきものを選んで全部実装」。

## Global Constraints

- 公開（pages.yml）を止める変更は入れない。新しい検査は `continue-on-error`。
- 予想のルール・買い目・成績の計算（scraper/score.py）は変えない。
- 画面の文言はユーザー目線の言葉にする（内部用語を出さない）。
- 広告（AdSense）と GA4・Search Console の設定には触れない。
- URL は変えない。

## Review Focus

- レース名が空・1語だけ・全角混じりでも `tidy_race_name` が落ちない（Task 1 のテスト）。
- 「Google にだけ載せない」ページが0件でも noindex 用サイトマップが壊れた XML にならない（Task 2）。
- 発走時刻が1つも無い日は、古い表示の警告がこれまでどおり出る（Task 4）。
- 直前の人気が無いレースは基準の比較から外し、0件なら欄ごと出さない（Task 7）。
- 払戻が購入額と同額のとき「元返し」、少ないとき「トリガミ」のまま（Task 3）。

---

### Task 1: レース名の整形（19）
**Files:** Create `site/sitekit.py`、Test `tests/test_sitekit.py`、Modify `site/build.py`（`race_label`・`race_short`）
**Interfaces:** Produces `tidy_race_name(name: str) -> str`（NFKC・空白の整理・同じ語の連続を1つに・単独の「重賞」を外す）
- [ ] テスト：`"Ｃ２二 Ｃ２二 ３歳以上" -> "C2二 3歳以上"`、`"兵庫ジュニアグランプリ（Ｊｐｎ２） 重賞 ２歳登録馬" -> "兵庫ジュニアグランプリ(Jpn2) 2歳登録馬"`、`"重賞" -> "重賞"`、`"" -> ""`
- [ ] 失敗を確認 → 実装 → 成功を確認 → build.py の2か所で使う → commit

### Task 2: Google に載せないページ用のサイトマップ（1）
**Files:** `site/sitekit.py`、`tests/test_sitekit.py`、`site/build.py`（`page()` で記録、`build()` の最後で書き出し）
**Interfaces:** Produces `hidden_since(race_date, days, policy_start) -> str` と `noindex_sitemap(pages: dict[path, 変わった日], base_url, today_iso, days=90) -> str`（実装時に変更。経緯は ledger の Ruling）
- [x] テスト：変わった日の計算、最初から載せないページ（""）は入れない、90日を過ぎたら外す、0件で空の `<urlset>`、`&` のエスケープ
- [x] build.py：`page(..., hidden=)` で `NOINDEX_PAGES` に記録し、`/sitemap-noindex.xml` を毎回出す。robots.txt には書かない（Bing に知らせないため。Search Console から送る）

### Task 3: 元返しの表示（23）
**Interfaces:** Produces `result_badge(stake: int, ret: int, roi: str) -> tuple[str, str]`（クラス名, 文言）。`ret == stake` は `("hit even", "的中・元返し ±0円")`（当日の自動更新が .res.hit を結果の印に使うため hit を残す）
- [ ] テスト：外れ・トリガミ・元返し・的中の4通り → 実装 → `race_item` とレースページの結果行で使う

### Task 4: 「最終更新から時間がたっています」の出し方（29）
（実装時に変更：サーバー側の値は作らず、JS だけで判断する）
- [x] JS は「6時間超」かつ「発走時刻の付いたレースが無い、または発走を過ぎても結果が無いレースがある」ときだけ出す
- [ ] `tests/site_smoke_js.py`：時計を固定して、発走前は出ない・発走後は出ることを確認

### Task 5: 目次の「×」（28）、厳選0件の日（31）、依存症の相談先（54）、買い方ガイドへの案内（12）、Webフォント（26）
**Files:** `site/build.py`、`site/weekly.py`、`tests/site_smoke.py`、`tests/site_smoke_js.py`
- [ ] smoke（静的）：フッターに相談先のリンク／厳選0件の日に `gensen-box` のカードが無い／G1特集の「次に見る」に買い方ガイド／Web フォントを読み込まない（実装時に変更：optional でも書体が混ざるため、端末の明朝体にした）／h1 に同じ語の連続が無い
- [ ] smoke（JS）：レースページの目次に1文字の項目が無い
- [ ] 失敗を確認 → 実装 → 成功を確認

### Task 6: コラムを RSS に（18）、ビルドの大きさの記録（62）
**Interfaces:** Produces `column_feed(cols: list[dict], limit: int = 15) -> list[tuple[str, str, str]]`（path, title, YYYY-MM-DD。下書きと日付なしは除く、新しい順）、`dir_stats(root: Path) -> dict`（`bytes`・`files`）
- [ ] テスト → 実装 → build.py で feed.xml に足す、`/build-stats.json` を書く
- [ ] `.github/workflows/size.yml`：毎日1回 `build-stats.json` を見て、800MB か 19,000 ファイルを超えたら失敗にする（alert.yml の対象に足す）

### Task 7: 「1番人気を買うだけ」との比較（21）
**Interfaces:** Produces `favorite_baseline(rows: Iterable[dict]) -> dict`。`rows` の各要素は `pop`（馬番→人気）、`payouts`、`stake`、`ret`、`honmei`、`jra`。戻り値は `{"all"|"jra"|"nar": {"n", "fuku", "tan", "site", "same"}}`（回収率は%の小数、0件の区分は入れない）
- [ ] テスト：複勝・単勝の払戻の合算、人気なしの行を除く、0件、中央と地方の区分
- [ ] build.py：買い方別のページに「比較の基準」の欄を足す（今のルールの期間・直前の人気があるレースだけ）

### Task 8: 仕上げ
- [ ] `python tests/test_scoring.py`、`python -m pytest tests -q`、`node --test tests/racesim.test.js`
- [ ] フルビルド → `tests/site_smoke.py` と `tests/site_smoke_js.py` → 画面確認
- [ ] 更新履歴（changelog）に読者向けの説明を1件、pages.yml に smoke を `continue-on-error` で追加
