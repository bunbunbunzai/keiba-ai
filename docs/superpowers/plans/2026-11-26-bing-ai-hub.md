# 特集まとめの強化（よくある質問・G1以外の重賞） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 特集まとめ（〇〇<年>-guide）に「よくある質問」を自動で入れ、G1以外のJRAの重賞にも特集まとめを1レース1本、Googleに載せない設定で自動作成する。

**Architecture:** よくある質問は、事実と文面を1つのモジュール（`site/hubfaq.py`。副作用なし）に集め、`site/column.py` がサイトを組み立てるときに記事の本文（Markdown）へ差し込む。G1以外の重賞は、`scraper/g1_hub_cols.py` の `build_next`（金杯で動いている形）に設定を自動で渡して作り、頭書きの `hub: auto` を目印に `site/column.py` が「特集」として登録し、Googleにだけ載せない。

**Tech Stack:** Python 3.12（標準ライブラリのみ）。テストは pytest でも `python tests/<file>.py` でも動く形。

**Spec:** `docs/superpowers/specs/2026-11-26-bing-ai-hub-design.md`

## Global Constraints

- 文は「である」調。内部の用語（phase・hub・noindex など）を読者向けの文に出さない。
- 事実は `site/hubfaq.py` の定数に出どころのURLと確認日（2026-11-26）を残す。確かめていないことは書かない。
- ネット投票の発売開始の時刻を書くのは、表を確かめた年（`SALE_YEAR = 2026`）のレースだけ。
- 発走時刻は、データ（出馬表・予想）か記事の予定時刻があるときだけ書く。無ければ時刻を書かない。
- G1以外の重賞の特集まとめは Google にだけ noindex、サイトマップに入れない、IndexNow の一覧には入れる。
- 作り始めはレースの35日前（`HUB_DAYS = 35`）、作り直しはレースの14日後まで（`HUB_KEEP = 14`）、過去の開催が8回未満（`HUB_MIN_YEARS = 8`）のレースは作らない。
- よくある質問の処理が失敗しても、サイトの組み立ては止めない（質問を出さないだけにする）。
- 1ページに同じPRを2つ出さない。
- 既存のテスト（test_scoring・test_social_threads・test_racesim・racesim.test.js）が通ったままであること。

## Review Focus

1. 日程が分からない特集まとめ（重賞の一覧にも頭書きにも日付が無い）→ 質問を出さない（「None」を表示したり落ちたりしない）。→ Task 1 `test_no_date_no_faq`
2. 発走が15時より前・16時以降のレース（中山大障害など）→ 地上波の放送時間に入ると書かない。→ Task 1 `test_post_outside_tv_window`
3. 土日以外のレース（1/4の金杯、12/29の東京大賞典）と2027年のレース → 土日の番組名を書かない、2026年の発売時刻を書かない。→ Task 1 `test_weekday_race`・`test_sale_time_only_for_checked_year`
4. 手で作った特集まとめと自動の特集まとめが同じレース・同じ年で重なる（金杯）→ 自動の方を作らない。→ Task 3 `test_skips_manual_guide`
5. レースの日を過ぎたが結果がまだ入っていない → 「これから」の質問を出さない。→ Task 1 `test_past_race_no_faq`

---

### Task 1: よくある質問の文面（site/hubfaq.py）

**Files:**
- Create: `site/hubfaq.py`
- Test: `tests/test_hub_faq.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `faq_items(info: dict) -> list[dict]`：`[{"q": 質問, "a": 答え（Markdownの1段落）, "after": 答えの次の行に置く差し込み（"{{aff_nar}}" か ""）}]`。出さないときは `[]`。
  - `faq_md(info: dict) -> str`：`## <名前><年>のよくある質問` で始まるMarkdown。出さないときは `""`。
  - `faq_ld(info: dict) -> dict | None`：schema.org の FAQPage。答えはリンク記法を外した文字だけ。
  - `insert_md(body: str, faq: str) -> str`：`## 特集の記事` の前、無ければ `## 出典` の前、それも無ければ末尾。
  - `post_hint(body: str) -> str`：本文の「15:40発走」「15時40分発走」から `"15:40"`。無ければ `""`。
  - `info` の形：`{"slug", "name", "year"(str), "date"(YYYYMMDD), "venue"(例 "東京"), "course"(例 "芝2400m"), "grade", "jra"(bool), "post"("15:40" か ""), "post_fixed"(bool), "phase"(None/"entries"/"runners"/"waku"/"pred"/"result"), "pred_path", "publish"(weekly.publish_when の文), "today"(YYYYMMDD), "graded_page"(bool)}`

- [ ] **Step 1: テストを書く**（`tests/test_hub_faq.py`。`jc()`＝2026-11-29（日）東京・芝2400m・G1・jra・post "15:40"・post_fixed False・today "20261126" の info を返す補助）
  - `test_jra_sunday_g1`：質問は6つ。1つ目の答えに「11月29日（日）」「東京競馬場」「芝2400m」「15時40分」「予定」。中継の答えに「みんなのKEIBA」「無料」。金額の答えに「100円」「20歳」。ネットの答えに「即PAT」「金曜の18時30分」「1分前」。
  - `test_post_fixed_wording`：`post_fixed=True` なら1つ目の答えに「予定」が無い。
  - `test_no_post_time`：`post=""` なら答えに「時」「分」で終わる時刻が無く、「出馬表」を含む。
  - `test_saturday_race`：2026-12-26（土）→「ウイニング競馬」を含み「みんなのKEIBA」を含まない。
  - `test_weekday_race`：2027-01-04（月）→ どちらの番組名も含まず、「土曜・日曜以外」を含む。
  - `test_post_outside_tv_window`：`post="14:40"` →「放送時間」と「入らない」を含む。
  - `test_sale_time_only_for_checked_year`：2027年の日曜G1 →「18時30分」を含まず「1分前」は含む。2026年の日曜G3 →「土曜の7時」。
  - `test_pred_published`：`phase="pred"`, `pred_path="/2026/11/29/tokyo/12r/"` → AI予想の答えにそのリンクと「公開中」。
  - `test_local_race`：`jra=False`, 大井, `slug="tokyo-daishoten"` →「楽天競馬」「SPAT4」「地方競馬ライブ」、`after == "{{aff_nar}}"` の項目がちょうど1つ、「即PAT」は「2025年」と一緒に出る、競馬場で見る質問は無い。
  - `test_result_no_faq`・`test_past_race_no_faq`・`test_no_date_no_faq`：`faq_items == []`、`faq_md == ""`、`faq_ld is None`。
  - `test_md_and_ld`：`faq_md` は `## ジャパンカップ2026のよくある質問` で始まり、`###` が質問の数だけある。`faq_ld` は `@type == "FAQPage"`、`mainEntity` の数が同じ、答えに `](` と `{{` が無い。
  - `test_insert_md`：`## 特集の記事` の直前／無ければ `## 出典` の直前／どちらも無ければ末尾。`faq=""` なら本文は変わらない。
  - `test_post_hint`：`"15:40発走予定" → "15:40"`、`"15時40分発走予定" → "15:40"`、`"9時5分"` は発走が無いので `""`。
- [ ] **Step 2: 失敗を確かめる** `python -m pytest tests/test_hub_faq.py -q` → `ModuleNotFoundError: hubfaq`
- [ ] **Step 3: `site/hubfaq.py` を書く。** 定数 `CHECKED = "2026-11-26"`、`SALE_YEAR = 2026`、`SRC`（JRAのURL：tvradio・racelive・soku/about・soku/instructions/hatsubai/jra・kouza/baken・ticket・news/202512/121402）、`NAR_NOTES = {"tokyo-daishoten": …}`。文面は設計メモ「決めたこと」のとおり。地上波の放送時間は 15:00〜16:00。
- [ ] **Step 4: 通ることを確かめる** `python -m pytest tests/test_hub_faq.py -q` と `python tests/test_hub_faq.py`
- [ ] **Step 5: Commit** `よくある質問の文面（site/hubfaq.py）とテスト`

### Task 2: 特集まとめへの差し込み（site/weekly.py・site/column.py）

**Files:**
- Modify: `site/weekly.py`（`hub_info` を追加）
- Modify: `site/column.py`（`build()` の記事ごとの処理、`_aff_for`）
- Test: `tests/test_hub_faq.py`（`_aff_for` の分）＋手元の組み立て

**Interfaces:**
- Consumes: Task 1 の `faq_md`・`faq_ld`・`insert_md`・`post_hint`
- Produces: `weekly.hub_info(slug: str, year: str, meta: dict | None = None, post_hint: str = "") -> dict | None`（Task 1 の `info` の形。日程が分からなければ `None`）

- [ ] **Step 1: テストを足す** `test_aff_for_skips_when_faq_has_pr`：`column._aff_for({"slug": "x-guide", "race_venue": "大井", "body": "", "_faq_pr": True}, {"aff_rakuten": "R", "aff_saikyo": "S"}) == ""`、`_faq_pr` が無ければ `"R"`。
- [ ] **Step 2: 失敗を確かめる**
- [ ] **Step 3: 実装**
  - `weekly.hub_info`：`hub_top` と同じ決まりで名前・日付・場・コース・格を求める（JRAは `_K`、無ければ `meta`）。`post` は予想の出馬表→`WAKU`→`post_hint` の順で、前の2つなら `post_fixed=True`。`phase` は結果があれば `"result"`、予想があれば `"pred"`、ほかは `hub_phase` の値。
  - `column.build()`：`tables["aff_nar"] = build.aff_line("nar")`。特集まとめ（`-guide` かつ `series in weekly.FEATURE_RACE`）では、`render` の前に `hubfaq.insert_md(本文, hubfaq.faq_md(info))` を通し、`faq_ld` があれば `head_extra` に足す。`"{{aff_nar}}"` を差し込んだ記事は `c["_faq_pr"] = True`。全体を `try/except` で包む。
  - `column._aff_for`：`c.get("_faq_pr")` なら `""`。
- [ ] **Step 4: 確かめる** `python -m pytest tests/test_hub_faq.py -q`、`python site/build.py` のあと `_site/column/jc2026-guide/index.html` に「ジャパンカップ2026のよくある質問」と `FAQPage` があり、`_site/column/mile2026-guide/index.html` に無い。`_site/column/tokyo-daishoten2026-guide/index.html` の `data-aff='rakuten-keiba-banner'` を含む箱が1つ。
- [ ] **Step 5: Commit** `特集まとめに「よくある質問」を差し込む`

### Task 3: G1以外の重賞の特集まとめを作る（scraper/g1_hub_cols.py）

**Files:**
- Modify: `scraper/g1_hub_cols.py`
- Test: `tests/test_hub_auto.py`

**Interfaces:**
- Consumes: 既存の `build_next(cfg, all_, K, today)`・`write(...)`・`past10`
- Produces:
  - `auto_hero(r: dict) -> str`：障害 `g-jump`、ダート `g-dirt-day`、芝1400m以下 `g-sprint`、芝3000m以上 `g-stayer`、ほかは月で `g-turf-spring`(3〜5)／`summer`(6〜8)／`autumn`(9〜11)／`winter`(12〜2)。
  - `auto_cfgs(K: dict, today: str, cols: Path = COLS) -> list[dict]`：`{"series": "<slug><年>", "slug", "hero", "ahead": HUB_DAYS, "keep": HUB_KEEP, "auto": True}` をレースの日付順に。`today` は `YYYY-MM-DD`。
  - 自動の記事の頭書き：`race: <slug>`、`hub: auto`（ほかは今の `extra` と同じ）。

- [ ] **Step 1: テストを書く**（リポジトリの `data/graded_hist` を読む。日付は引数で固定する）
  - `test_window_and_grades`：`today="2026-11-26"` → `stayers-stakes`・`keihan-hai`・`hanshin-cup` を含み、`japan-cup`・`arima-kinen`（G1）と `fairy-stakes`（45日先）を含まない。全部 `auto is True`。
  - `test_skips_manual_guide`：`today="2026-12-20"` → `nakayama-kimpai`・`kyoto-kimpai` を含まない（手で作った特集まとめがある）。空のフォルダを `cols` に渡すと含む。
  - `test_skips_short_history`：`today="2027-01-10"` → `kokura-himba-stakes`（過去2回）を含まない。
  - `test_keep_after_race`：`today="2026-12-10"` → `stayers-stakes`（12/5。5日後）を含む。`today="2026-12-25"` → 含まない（20日後）。
  - `test_auto_hero`：障害・ダート・芝1200m・芝3600m・1月の芝2000m の5つ。
  - `test_build_auto`：`stayers-stakes2026` を `today="2026-11-26"` で組み立てる → 記事名 `stayers-stakes2026-guide`、題名は「ステイヤーズステークス2026はいつ？日程と過去10年の傾向【特集まとめ】」（「前哨戦」が無い）、本文に `## レースの基本情報`・`## 2025年の結果`・`## 過去10年の勝ち馬`、`/column/g1-nittei-2027/` へのリンクが無い、`extra["hub"] == "auto"`・`extra["race"] == "stayers-stakes"`。
  - `test_next_unchanged`：`NEXT` の `feb2027` を組み立てた題名に「前哨戦」が残る（既存の特集まとめは変えない）。
- [ ] **Step 2: 失敗を確かめる** `python -m pytest tests/test_hub_auto.py -q`
- [ ] **Step 3: 実装** `HUB_DAYS = 35`、`HUB_KEEP = 14`、`HUB_MIN_YEARS = 8`、`HUB_GRADES = ("G2", "G3", "J・G2", "J・G3")`。`build_next` は `cfg.get("ahead", AHEAD_DAYS)`・`cfg.get("keep")`・`cfg.get("about")`・`cfg.get("auto")` を見る（題名と説明文の「前哨戦」は表があるときだけ。自動の記事は `/weekend/` と `/graded/` へ案内する。名前はレースガイドが無ければ `G.expand`）。`main()` に `auto_cfgs` の分を足す。
- [ ] **Step 4: 通ることを確かめる** 上のテストと、`cd scraper && python g1_hub_cols.py`（8本前後できる）。
- [ ] **Step 5: Commit** `G1以外の重賞の特集まとめを自動で作る`

### Task 4: 自動の特集まとめをサイトに載せる（site/column.py・site/weekly.py・site/build.py）

**Files:**
- Modify: `site/column.py`（`FEATURE_SERIES`・`register_auto_hubs`・`_hidden_hub`・関連記事・一覧）
- Modify: `site/weekly.py`（`prepare` で登録、名前の略し方）
- Modify: `site/build.py`（llms.txt の特集の一覧）
- Test: `tests/test_hub_auto.py`

**Interfaces:**
- Consumes: Task 3 の頭書き（`hub: auto`・`race`・`series`）
- Produces:
  - `column.register_auto_hubs(cols: list[dict] | None = None) -> tuple[str, ...]`：自動の特集まとめの series を `weekly.FEATURE_RACE`・`column.FEATURE_IDS`・`column.FEATURE_GROUP["jusho"]` に登録して返す。何度呼んでも同じ結果。
  - `column._hidden_hub(c: dict) -> bool`

- [ ] **Step 1: テストを足す**
  - `test_register_auto_hubs`：`[{"slug": "x2026-guide", "series": "x2026", "hub": "auto", "race": "x", "draft": False}, {"slug": "y", "series": "y2026", "draft": False}]` → 戻り値 `("x2026",)`、`weekly.FEATURE_RACE["x2026"] == "x"`、`"x2026" in column.FEATURE_IDS`、`"y2026" not in column.FEATURE_IDS`、既存の `"jc2026"` は残る。
  - `test_hidden_hub`：`{"hub": "auto", "race_grade": "G3"}` → True、`{"hub": "auto", "race_grade": "G1"}` → False、`{"race_grade": "G3"}` → False。
- [ ] **Step 2: 失敗を確かめる**
- [ ] **Step 3: 実装** `FEATURE_SERIES` の末尾に `("jusho", "重賞の特集まとめ（G2・G3）", …)`。`weekly.prepare` は `FEAT` を作る前に `column.register_auto_hubs()` を呼ぶ。`build()` の `hide` に `_hidden_hub(c)` を足す。関連記事：G1などの特集のページでは今の「ほかの特集」（自動の分を除いて6本）に「近く行われる重賞（G2・G3）の特集まとめ」4本を足し、自動の特集まとめでは同じレースのデータ記事・近いG1の特集4本・ほかの自動の特集まとめ4本。llms.txt は `FEATURE_GROUP` の記事がある見出しも載せる。
- [ ] **Step 4: 確かめる** テストと `python site/build.py`：`_site/column/stayers-stakes2026-guide/index.html` に `<meta name="googlebot" content="noindex">` があり、`_site/sitemap.xml` に無く、`_site/indexnow-state.json` にある。`_site/column/index.html` に「重賞の特集まとめ（G2・G3）」。`_site/column/jc2026-guide/index.html` の「ほかの特集」に有馬記念が残っている。基準の組み立て（変更前）と比べ、関係のないページ（/graded/・/weekend/・トップ）の差が意図したリンクの追加だけであること。
- [ ] **Step 5: Commit** `G1以外の重賞の特集まとめをサイトに載せる（Googleには載せない）`

### Task 5: 記事を作って確認し、反映する

- [ ] `cd scraper && python g1_hub_cols.py` でできた `columns/*-guide.md` を確かめて commit。
- [ ] 全テスト（既存4つ＋新しい2つ）と `python site/build.py`。出来上がったページを実際に開いて読む（JC・東京大賞典・ステイヤーズS・コラムの一覧）。
- [ ] ブランチを push し、プルリクエストを作って main に入れる。公開の処理（pages）が成功し、本番のページに反映されたことを確かめる。
- [ ] ジャパンカップ週の振り返り（設計メモの3つ目）を、12月2日（水）20時にこのやり取りへ届くように予約する（コードの変更は無い）。
