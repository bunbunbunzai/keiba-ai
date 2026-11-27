# keiba-ai

**[競馬全頭ログ](https://www.ai-keiba-log.com/)** のプログラムとデータ。日本で開催される競馬（JRA・地方）の全レースをAI（Claude）が毎日予想し、外れも含めた全予想の成績と回収率を公開している。

- サイト：https://www.ai-keiba-log.com/
- [今日の予想](https://www.ai-keiba-log.com/) ／ [成績・回収率](https://www.ai-keiba-log.com/results/) ／ [重賞のAI予想](https://www.ai-keiba-log.com/graded/) ／ [買い方別の回収率](https://www.ai-keiba-log.com/strategy/) ／ [予想の方法](https://www.ai-keiba-log.com/about/)

## 仕組み

1. **取得**（GitHub Actions・プログラム）：JRA公式サイトと楽天競馬から、出馬表・近走・オッズ・結果を取得し `data/` に保存
2. **分析**（Claude）：整形済みデータから評価点・印・買い目を作成し `predictions/` に保存（手順は `PREDICT.md`）
3. **集計**（プログラム）：レースの結果と照合し、回収率を記録（`data/results/`・`results_ledger.csv`）
4. **公開**：`site/build.py` で静的サイトを作り、GitHub Pages で公開

## 取得の方針

- 各サイトの robots.txt とアクセス間隔の指定を守る（楽天競馬は60秒に1ページ、JRAは3秒に1ページ）
- 取得したデータは分析の材料にのみ使い、サイトには独自の印・評価・成績だけを掲載する
