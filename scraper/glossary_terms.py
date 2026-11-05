"""用語集（/glossary/<slug>/）にする一般的な競馬用語。カテゴリごとに (slug, 用語)。"""

TERMS = {
    "馬券の種類と買い方": [
        ("tansho", "単勝"), ("fukusho", "複勝"), ("wakuren", "枠連"), ("umaren", "馬連"), ("wide", "ワイド"), ("umatan", "馬単"),
        ("sanrenpuku", "3連複"), ("sanrentan", "3連単"), ("win5", "WIN5"), ("box", "ボックス買い"), ("nagashi", "流し"),
        ("formation", "フォーメーション"), ("multi", "マルチ"), ("jiku", "軸馬"), ("aite", "相手（ヒモ）"),
    ],
    "オッズ・払戻・成績": [
        ("odds", "オッズ"), ("ninki", "人気"), ("haraimodoshi", "払戻金"), ("kojoritsu", "控除率（払戻率）"), ("kitaichi", "期待値"),
        ("kaishuritsu-gen", "回収率"), ("tekichuritsu", "的中率"), ("shoritsu", "勝率"), ("rentairitsu", "連対率"), ("fukushoritsu", "複勝率（3着内率）"),
        ("henkan", "返還"), ("tokubarai", "特払い"), ("kaime", "買い目"), ("ten", "点数"), ("ganpon", "元返し"),
    ],
    "レースの種類とクラス": [
        ("g1", "GⅠ（G1）"), ("jushou", "重賞"), ("jpn", "JpnⅠ・JpnⅡ・JpnⅢ"), ("listed", "リステッド競走"), ("open", "オープン"),
        ("shinba", "新馬戦"), ("misho", "未勝利戦"), ("class-jra", "1勝クラス・2勝クラス・3勝クラス"), ("chiho-class", "地方競馬のクラス（A・B・C）"),
        ("handicap", "ハンデ戦"), ("betsutei", "別定"), ("teiryo", "定量"), ("barei-race", "馬齢戦"), ("tokubetsu", "特別競走"),
        ("koryu", "交流重賞"), ("trial", "トライアル（前哨戦）"), ("sankan", "三冠"),
    ],
    "コースと馬場": [
        ("shiba", "芝"), ("dirt", "ダート"), ("shogai", "障害"), ("baba", "馬場状態"), ("omo-baba", "重馬場・不良馬場"),
        ("migimawari", "右回り・左回り"), ("chokusen", "最後の直線"), ("saka", "坂"), ("uchiwaku", "内枠・外枠"),
        ("kyori", "距離区分（短距離・マイル・中距離・長距離）"), ("nighter", "ナイター競馬"), ("banei", "ばんえい競馬"),
        ("kaisai", "開催（〇回〇日）"), ("course-gawari", "コース替わり（Bコース・Cコース）"), ("jiba", "地方競馬と中央競馬"),
    ],
    "展開と脚質": [
        ("nige", "逃げ"), ("senko", "先行"), ("sashi", "差し"), ("oikomi", "追い込み"), ("makuri", "まくり"), ("hana", "ハナ"),
        ("pace", "ペース（ハイペース・スローペース）"), ("agari", "上がり3ハロン"), ("tsukajun", "通過順"), ("chakusa", "着差"),
        ("deokure", "出遅れ"), ("furi", "不利"), ("tenkai", "展開"), ("kyakushitsu", "脚質"), ("ichitori", "位置取り"),
    ],
    "馬・体調・血統": [
        ("bataiju", "馬体重"), ("kinryo", "斤量"), ("yasumiake", "休み明け"), ("rento", "連闘"), ("tataki", "叩き2戦目"),
        ("tennyu", "転入・転厩"), ("ketto", "血統"), ("chichi", "父・母父"), ("chokyo", "調教・追い切り"), ("paddock", "パドック"),
        ("kaeshiuma", "返し馬"), ("torikeshi", "出走取消・競走除外"), ("kouchaku", "降着・失格"), ("seire", "性齢（牡・牝・セン）"),
        ("kyoso-ba", "競走馬の年齢とキャリア"),
    ],
    "人と予想": [
        ("kishu", "騎手"), ("norikawari", "乗り替わり"), ("genryo", "減量騎手（見習い騎手）"), ("chokyoshi", "調教師・厩舎"),
        ("banushi", "馬主"), ("shirushi-gen", "印（◎〇▲△）"), ("honmei", "本命"), ("ana", "穴馬"), ("katai", "堅いレース・荒れるレース"),
        ("data-yoso", "データ予想"), ("ai-yoso", "AI予想"), ("kako-kekka", "過去のレース結果の見方"), ("shutsuba", "出馬表の見方"),
        ("netto", "ネット投票"), ("ukeoi", "予想の的中率と回収率の違い"),
    ],
}
