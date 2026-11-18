"""「AI vs あなた」月間ランキングのページ（/vs/）と、レースページの◎をランキングに記録する部品。

読者が各レースページで選んだ◎を league/ の API（Cloudflare Workers）に記録し、月ごとに
  - 順位：選んだ◎の単勝を100円ずつ買ったとしたときの回収率（MIN_PICKS レース以上）
  - AIとの対戦成績：同じレースでの◎どうしの着順くらべ
を出す。レース・発走時刻・結果・払戻は、このサイトが公開する /vsgame/<日付>.json を API が読む（手入力なし）。
LEAGUE_URL（API のURL）が設定されているときだけ作る。一般公開（VS_PUBLIC=1）までは noindex で、
プレビュー用のコードを入れた人にしか見えない（レースページの表示も変わらない）。
"""
from __future__ import annotations

import json

MIN_PICKS = 1  # ランキングに載る最少レース数（表示用。実際の判定は API 側：league/wrangler.toml の VS_MIN_PICKS）。いまは下限なし

RULES = f"""
<section class='card' id='rules'><h2>ルール</h2><p><a href='/vs/guide/'>はじめての方へ：遊び方と順位の決まり方（全頭くんの案内）</a></p><ul>
<li><b>参加のしかた</b>：下で名前を決めたら、各レースページの「AI vs あなた」で◎を1頭選ぶだけ。発走時刻までなら選び直せます。発走後は変えられません。</li>
<li><b>順位は回収率</b>：その月に選んだ◎の単勝を、1レース100円ずつ買ったとして計算します（払戻の合計÷購入額の合計）。人気薄を当てるほど上がります。</li>
<li><b>ランキングの対象</b>：その月に1レースでも結果が出た人は全員（レース数の下限はありません）。</li>
<li><b>AIとの対戦成績</b>：同じレースで、あなたの◎とAIの◎の着順をくらべます。着順が上なら勝ち、同じ馬・同着なら引き分け。順位には使いませんが、ランキングに並べて出します。</li>
<li><b>取消・除外・中止</b>：選んだ馬が出走取消・競走除外になったレースと、払戻の無かったレースは、買わなかった扱いで数えません。</li>
<li><b>結果と払戻</b>：このサイトの成績と同じデータで自動集計します（確定から反映まで数分〜10分ほど）。正式な結果は主催者の発表をご確認ください。</li>
<li><b>同じ成績のとき</b>：回収率が同じなら的中数、それも同じならレース数の多い人が上。すべて同じなら同じ順位です。</li>
<li>参加は無料で、賞品はありません。馬券の購入は参加の条件ではありません。1人1つの名前でお願いします。不適切な名前は運営が変更・削除することがあります。</li>
<li>ランキングのために保存するのは、決めた名前と、選んだ◎の記録だけです。メールアドレスなどの個人情報は集めません。</li>
<li>登録情報は、いまお使いのブラウザに保存されます。ほかの端末でも続けたいときは、下の「引き継ぎ」を使ってください。</li>
</ul></section>
"""

CSS = """
.vs-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}
.vs-kpis div{background:var(--panel);border:1px solid var(--line);padding:10px 8px;text-align:center}
.vs-kpis b{display:block;font-size:20px;line-height:1.3}.vs-kpis span{font-size:12px;color:var(--mut)}
@media (max-width:520px){.vs-kpis{grid-template-columns:repeat(2,1fr)}}
.vs-form{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.vs-form input{flex:1 1 180px;min-width:0;padding:10px;border:1px solid var(--line);background:var(--panel);color:inherit;font:inherit}
.vs-form button,.vs-btn{padding:10px 16px;border:0;background:var(--acc);color:var(--bg);font:inherit;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}
.vs-form button:disabled{opacity:.5}.vs-msg{min-height:1.5em;color:var(--hit)}
.vs-rank td,.vs-rank th{white-space:nowrap}.vs-rank td.nm{white-space:normal;word-break:break-all;min-width:6em}
.vs-rank tr.me td{background:var(--acc-soft);font-weight:700}.vs-rank tr.ai td{color:var(--mut)}
.vs-hist li{padding:8px 0;border-bottom:1px solid var(--line);list-style:none}.vs-hist{padding:0;margin:0}
.vs-hist .w{color:var(--hit);font-weight:700}.vs-months{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.vs-months a{padding:6px 10px;border:1px solid var(--line);text-decoration:none}.vs-months a[aria-current]{background:var(--rule);color:var(--bg)}
.vs-sv{margin:6px 0 0}
"""

JS = r"""(function(){
var app=document.getElementById('vs-app'),card=document.querySelector('.card.vs[data-api]');
var host=app||card;if(!host)return;
var API=host.dataset.api,PUB=host.dataset.public==='1',MIN=+host.dataset.min||20;
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v);}catch(e){}return null;}
function el(t,a,c){var e=document.createElement(t);if(a)for(var k in a){if(k==='text')e.textContent=a[k];else if(k==='cls')e.className=a[k];else e.setAttribute(k,a[k]);}
 (c||[]).forEach(function(x){if(x!=null)e.appendChild(typeof x==='string'?document.createTextNode(x):x);});return e;}
function api(m,p,b){var h={'content-type':'application/json'},t=ls('vs_token'),pv=ls('vs_pv');if(t)h.authorization='Bearer '+t;if(pv)h['x-league-preview']=pv;
 return fetch(API+p,{method:m,headers:h,body:b?JSON.stringify(b):undefined}).then(function(r){return r.json().then(function(j){j.status=r.status;return j;});})
  .catch(function(){return {ok:false,error:'通信できませんでした。時間をおいてからどうぞ。',status:0};});}
function ev(n,p){try{if(window.gtag)gtag('event',n,p||{});}catch(e){}}
function yen(n){return Number(n).toLocaleString('ja-JP');}
function pct(n){return Number(n).toFixed(1)+'%';}

/* ---------- レースページ：選んだ◎をランキングに記録する ---------- */
if(card&&!app){
 if(!PUB&&!ls('vs_pv'))return;                      /* 一般公開前は、プレビューのコードを入れた人だけ */
 var path=card.dataset.key.split(':').slice(2).join(':'),post=card.dataset.post,key=card.dataset.key;
 var note=el('p',{cls:'meta vs-sv'});card.insertBefore(note,card.querySelector('.r'));
 var now=function(){var d=new Date(Date.now()+9*3600e3);return d.toISOString().slice(0,16).replace(/[-T:]/g,'');};
 var named=ls('vs_name');
 if(!ls('vs_token')||!named){note.textContent='';note.appendChild(el('a',{href:'/vs/',text:'月間ランキングに参加する（名前を決めるだけ・無料）'}));note.appendChild(document.createTextNode('　'));note.appendChild(el('a',{href:'/vs/guide/',text:'遊び方'}));return;}
 note.textContent='ここで選んだ◎は、月間ランキングに記録されます（'+named+'）。';
 var lead=card.querySelector('p.meta');if(lead)lead.textContent=lead.textContent.replace('（選んだ馬は、いまお使いのブラウザにだけ保存されます）','');
 function send(n){api('POST','/api/vs/pick',{path:path,number:+n}).then(function(j){
  note.textContent=j.ok?'月間ランキングに記録しました（'+named+'）。':'ランキングには記録できませんでした：'+j.error;
  if(j.ok){note.appendChild(document.createTextNode(' '));note.appendChild(el('a',{href:'/vs/',text:'ランキングを見る'}));ev('vs_rank_pick',{race:card.dataset.label});}});}
 var btn=card.querySelector('.go'),sel=card.querySelector('select');
 if(btn)btn.addEventListener('click',function(){if(sel.value&&post>now())send(sel.value);});
 api('GET','/api/vs/pick?path='+encodeURIComponent(path)).then(function(j){
  if(!j.ok)return;var sv=j.data.number,lc=ls(key);
  if(sv!=null){note.textContent='';note.appendChild(document.createTextNode('月間ランキングに記録済み（◎'+sv+'番）。 '));note.appendChild(el('a',{href:'/vs/',text:'ランキングを見る'}));
   if(!lc){ls(key,String(sv));location.reload();}}
  else if(lc&&post>now())send(lc);                 /* 登録前にこのブラウザで選んでいた◎（発走前のものだけ） */
 });
 return;}

/* ---------- /vs/：ランキングと自分の成績 ---------- */
var ym=(new URLSearchParams(location.search).get('ym'))||new Date(Date.now()+9*3600e3).toISOString().slice(0,7);
function gate(msg){app.textContent='';
 var inp=el('input',{type:'text',placeholder:'プレビュー用のコード',autocomplete:'off','aria-label':'プレビュー用のコード'}),b=el('button',{type:'button',text:'入る'}),m=el('p',{cls:'vs-msg',text:msg||''});
 b.onclick=function(){if(!inp.value.trim())return;ls('vs_pv',inp.value.trim());load();};
 app.appendChild(el('section',{cls:'card'},[el('h2',{text:'準備中です'}),el('p',{text:'月間ランキングは公開前の確認中です。関係者の方は、プレビュー用のコードを入れてください。'}),el('div',{cls:'vs-form'},[inp,b]),m]));}
function nameForm(cur){
 var inp=el('input',{type:'text',maxlength:'12',placeholder:'ランキングに出す名前（2〜12文字）','aria-label':'ランキングに出す名前',value:cur||''}),b=el('button',{type:'button',text:cur?'名前を変える':'この名前で参加する'}),m=el('p',{cls:'vs-msg'});
 b.onclick=function(){var n=inp.value.trim();if(!n)return;b.disabled=true;m.textContent='';
  var go=function(){api('POST','/api/vs/name',{name:n}).then(function(j){b.disabled=false;if(!j.ok){m.textContent=j.error;return;}ls('vs_name',j.data.name);ev('vs_rank_join');load();});};
  if(ls('vs_token'))go();else api('POST','/api/register',{}).then(function(j){if(!j.ok){b.disabled=false;m.textContent=j.error;return;}ls('vs_token',j.data.token);go();});};
 return el('div',{},[el('div',{cls:'vs-form'},[inp,b]),m]);}
function kpis(s){var k=el('div',{cls:'vs-kpis'});
 [[pct(s.roi),'回収率'],[s.hits+'／'+s.n,'的中／レース'],[s.win+'勝'+s.lose+'敗'+(s.draw?s.draw+'分':''),'AIとの対戦'],[s.rank?s.rank+'位':'—','今月の順位']].forEach(function(x){k.appendChild(el('div',{},[el('b',{text:x[0]}),el('span',{text:x[1]})]));});return k;}
function meCard(d){var me=d.me,c=el('section',{cls:'card'},[el('h2',{text:'あなたの成績（'+ym.replace('-','年')+'月）'})]);
 if(!me||!me.name){c.appendChild(el('p',{text:'名前を決めると参加できます。決めたあとは、各レースページの「AI vs あなた」で◎を選ぶだけです。'}));c.appendChild(nameForm(''));return c;}
 ls('vs_name',me.name);
 c.appendChild(el('p',{cls:'meta',text:me.name+' さん'}));
 if(me.stats){c.appendChild(kpis(me.stats));
  c.appendChild(el('p',{cls:'meta',text:'購入'+yen(me.stats.stake)+'円 → 払戻'+yen(me.stats.ret)+'円'+(me.stats.rank?'':'。ランキングの対象まで、あと'+Math.max(0,d.min_picks-me.stats.n)+'レース')+(me.pending?'。結果待ち'+me.pending+'レース':'')}));}
 else c.appendChild(el('p',{text:me.pending?'結果待ちが'+me.pending+'レースあります。確定すると、ここに成績が出ます。':'今月はまだ◎を選んでいません。'}));
 c.appendChild(el('p',{},[el('a',{cls:'vs-btn',href:'/',text:'今日のレースで◎を選ぶ'})]));
 var det=el('details',{},[el('summary',{text:'名前を変える・ほかの端末に引き継ぐ'})]);det.appendChild(nameForm(me.name));
 var code=el('input',{type:'text',readonly:'',value:ls('vs_token')||'','aria-label':'引き継ぎコード'}),inp=el('input',{type:'text',placeholder:'引き継ぎコードを貼る','aria-label':'引き継ぎコードを貼る',autocomplete:'off'}),b=el('button',{type:'button',text:'この端末で続ける'}),m=el('p',{cls:'vs-msg'});
 b.onclick=function(){var t=inp.value.trim();if(!t)return;var old=ls('vs_token');ls('vs_token',t);api('GET','/api/vs/me').then(function(j){if(!j.ok||!j.data.name){ls('vs_token',old);m.textContent='引き継ぎコードが正しくありません。';return;}ls('vs_name',j.data.name);load();});};
 det.appendChild(el('p',{cls:'meta',text:'引き継ぎコード（人に見せないでください。これを知っている人は、あなたとして◎を選べます）'}));det.appendChild(el('div',{cls:'vs-form'},[code]));
 det.appendChild(el('p',{cls:'meta',text:'ほかの端末で使っているコードを、この端末に入れる'}));det.appendChild(el('div',{cls:'vs-form'},[inp,b]));det.appendChild(m);c.appendChild(det);
 return c;}
function rankCard(d,ai){var c=el('section',{cls:'card'},[el('h2',{text:ym.replace('-','年')+'月のランキング'})]);
 if(d.months&&d.months.length>1){var nav=el('nav',{cls:'vs-months','aria-label':'月を選ぶ'});d.months.forEach(function(m){var a=el('a',{href:'/vs/?ym='+m,text:m.replace('-','年')+'月'});if(m===ym)a.setAttribute('aria-current','page');nav.appendChild(a);});c.appendChild(nav);}
 c.appendChild(el('p',{cls:'meta',text:'◎の単勝を100円ずつ買ったときの回収率の順'+(d.min_picks>1?'（'+d.min_picks+'レース以上）':'')+'。参加'+d.players+'人のうち、AIに勝ち越しているのは'+d.beat_ai+'人。'}));
 var tb=el('tbody');
 function row(r,cls,rk){var tr=el('tr',cls?{cls:cls}:{},[el('td',{text:rk}),el('td',{cls:'nm',text:r.name}),el('td',{text:pct(r.roi)}),el('td',{text:r.hits+'／'+r.n}),el('td',{text:r.win==null?'—':r.win+'勝'+r.lose+'敗'+(r.draw?r.draw+'分':'')})]);tb.appendChild(tr);}
 d.ranked.forEach(function(r){row(r,r.me?'me':'',r.rank+'位');});
 if(ai&&ai.n)row({name:'AI（このサイトの◎）',roi:ai.roi,hits:ai.hits,n:ai.n,win:null},'ai','参考');
 if(!d.ranked.length)c.appendChild(el('p',{text:(d.min_picks>1?'まだ'+d.min_picks+'レースに届いた人がいません。':'まだ結果の出た参加者がいません。')+'最初の1人になれます。'}));
 c.appendChild(el('div',{cls:'scroll'},[el('table',{cls:'vs-rank'},[el('thead',{},[el('tr',{},[el('th',{text:'順位'}),el('th',{text:'名前'}),el('th',{text:'回収率'}),el('th',{text:'的中／レース'}),el('th',{text:'AIとの対戦'})])]),tb])]));
 if(ai&&ai.n)c.appendChild(el('p',{cls:'meta',text:'参考の行は、AIの◎の単勝を同じ月の全レースで100円ずつ買った場合（サイトの成績ページの買い目とは別の計算）。'}));
 return c;}
function histCard(h){var c=el('section',{cls:'card'},[el('h2',{text:'最近選んだ◎'})]),ul=el('ul',{cls:'vs-hist'});
 h.forEach(function(x){var t;if(!x.settled)t='結果待ち';else if(!x.counted)t=(x.finish==='取消'||x.finish==='除外'?x.finish:'払戻なし')+'（数えない）';
  else t=x.finish+'着'+(x.hit?'・的中 '+yen(x.ret)+'円':'')+(x.vs?'／AIの◎'+x.ai+'番は'+(x.ai_finish||'-')+(/^\d+$/.test(x.ai_finish||'')?'着':'')+' → '+({win:'あなたの勝ち',lose:'AIの勝ち',draw:'引き分け'})[x.vs]:'');
  ul.appendChild(el('li',{},[el('a',{href:x.path,text:x.post.slice(4,6)+'/'+x.post.slice(6,8)+' '+x.label}),el('br'),el('span',{cls:x.hit?'w':'',text:'◎'+x.number+'番：'+t})]));});
 if(!h.length)return null;c.appendChild(ul);return c;}
function load(){
 /* 公開かどうかは、ページに書かれた値ではなくサーバーの返事で決める（ブラウザに古いページが残っていても、コード欄を出さない） */
 /* 成績の取り込みはランキングを読むときに行われるので、履歴はそのあとに読む */
 Promise.all([api('GET','/api/vs/ranking?ym='+ym).then(function(j){return (ls('vs_token')&&j.ok?api('GET','/api/vs/history'):Promise.resolve({ok:true,data:{picks:[]}})).then(function(h){return [j,h];});}),
  fetch('/vsgame/ai-'+ym.replace('-','')+'.json').then(function(r){return r.ok?r.json():null}).catch(function(){return null})]).then(function(x){var a=[x[0][0],x[1],x[0][1]];
  var j=a[0];if(!j.ok){if(j.preview_required){var had=ls('vs_pv');ls('vs_pv',null);gate(had?'コードが正しくないようです。':'');return;}app.textContent='';app.appendChild(el('p',{cls:'vs-msg',text:j.error}));return;}
  app.textContent='';app.appendChild(meCard(j.data));app.appendChild(rankCard(j.data,a[1]));
  var h=a[2].ok?histCard(a[2].data.picks):null;if(h)app.appendChild(h);});}
load();
})();"""


def enabled(api_url: str) -> bool:
    return bool(api_url)


def race_attrs(api_url: str, public: bool) -> str:
    """レースページの「AI vs あなた」に足す属性と読み込み（API が無ければ空）。"""
    if not api_url:
        return ""
    return f" data-api='{api_url}' data-public='{'1' if public else '0'}' data-min='{MIN_PICKS}'"


SCRIPT = "<script src='/assets/versus.js' defer></script>"


def build(write, page, out_dir, api_url: str, site_name: str, public: bool, jsonld=None, zk_art=None, base_url: str = "") -> None:
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "assets" / "versus.js").write_text(JS, encoding="utf-8")
    (out_dir / "assets" / "versus.css").write_text(CSS, encoding="utf-8")
    body = ("<p class='crumb'><a href='/'>トップ</a> › AI vs あなた 月間ランキング</p><h1>AI vs あなた 月間ランキング</h1>"
            "<p class='answer'>各レースであなたの◎を1頭選び、AIの◎と勝負する。月ごとに、選んだ◎の単勝の回収率で順位を出す（参加無料）。"
            + ("<a href='/vs/guide/'>遊び方を見る</a>" if public else "") + "</p>"
            f"<div id='vs-app' data-api='{api_url}' data-public='{'1' if public else '0'}' data-min='{MIN_PICKS}'><p class='meta'>読み込み中…</p></div>"
            + RULES + SCRIPT)
    write("/vs/", page(f"AI vs あなた 月間ランキング｜{site_name}", body, "/vs/", noindex=not public,
                       desc="競馬全頭ログのAIの◎と、あなたの◎で勝負する月間ランキング。順位は単勝の回収率、AIとの対戦成績も表示。参加無料。",
                       head_extra="<link rel='stylesheet' href='/assets/versus.css'>"))
    if public and jsonld and zk_art:
        write("/vs/guide/", guide_page(page, jsonld, zk_art, site_name, base_url))


GUIDE_FAQ = [
    ("参加にお金はかかりますか", "かかりません。名前を決めるだけで参加できます。賞品はなく、馬券を買う必要もありません。"),
    ("何レース選べばランキングに載りますか", "1レースでも結果が出れば載ります。レース数の下限はありません。回収率が同じときは、的中数、レース数の多い人が上になります。"),
    ("◎はいつまで選べますか", "そのレースの発走時刻までです。それまでは何度でも選び直せます。発走後は変えられません。"),
    ("AIの◎と同じ馬を選んでもいいですか", "かまいません。その場合、AIとの対戦は引き分けになります。回収率にはそのまま数えます。"),
    ("選んだ馬が出走取消になったらどうなりますか", "そのレースは買わなかった扱いで、成績に数えません。払戻の無かったレースも同じです。"),
    ("結果はいつ反映されますか", "レースの結果がこのサイトに載ってから、1〜2分でランキングに反映されます。"),
    ("スマホとパソコンの両方で使えますか", "使えます。ランキングのページの「名前を変える・ほかの端末に引き継ぐ」にある引き継ぎコードを、もう一方の端末に入れてください。"),
    ("名前はあとで変えられますか", "変えられます。ランキングのページの「名前を変える・ほかの端末に引き継ぐ」から変更できます。ほかの人が使っている名前は使えません。"),
    ("AIの成績は載りますか", "ランキングの表のいちばん下に、参考として「AIの◎の単勝を同じ月の全レースで買った場合」の回収率を出しています。順位は付きません。"),
]


def guide_page(page, jsonld, zk_art, site_name: str, base_url: str) -> str:
    faq = "".join(f"<h3>{q}</h3><p>{a}</p>" for q, a in GUIDE_FAQ)
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in GUIDE_FAQ]}
    bc = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": site_name, "item": base_url + "/"},
        {"@type": "ListItem", "position": 2, "name": "AI vs あなた 月間ランキング", "item": base_url + "/vs/"},
        {"@type": "ListItem", "position": 3, "name": "遊び方", "item": base_url + "/vs/guide/"}]}
    body = (
        "<p class='crumb'><a href='/'>トップ</a> › <a href='/vs/'>AI vs あなた 月間ランキング</a> › 遊び方</p>"
        "<h1>AI vs あなた 月間ランキングの遊び方</h1>"
        "<p class='answer'>「AI vs あなた 月間ランキング」は、競馬全頭ログのAIが出す◎（本命）と、あなたが選ぶ◎で勝負する無料の企画。"
        "各レースで◎を1頭選ぶと、月ごとに「◎の単勝の回収率」で順位が出て、AIとの対戦成績（3勝2敗のような形）も記録される。</p>"
        + zk_art("trophy", "<p><b>全頭くん</b>：僕（AI）の◎は毎日全レースで公開しています。同じレースであなたの◎を1頭選んで、どっちが当たるか勝負しましょう。"
                           "名前を決めるだけで、すぐ始められます。</p>")
        + "<p><a class='vs-btn' href='/vs/'>ランキングを見る・参加する</a></p>"
        "<section class='card'><h2>遊び方（3ステップ）</h2><ol>"
        "<li><b>名前を決める</b>：<a href='/vs/'>ランキングのページ</a>で、ランキングに出す名前（2〜12文字）を入れます。メールアドレスなどの登録は要りません。</li>"
        "<li><b>レースページで◎を選ぶ</b>：<a href='/'>今日の予想</a>から好きなレースを開き、ページの下のほうにある「AI vs あなた」で馬を1頭選んで「この馬に決める」を押します。"
        "AIの◎・全頭の評価・オッズは同じページで見られます。</li>"
        "<li><b>結果を待つ</b>：レースが確定すると、そのレースページに勝敗が出て、ランキングにも反映されます。</li></ol>"
        "<p class='meta'>何レース選んでもかまいません。1日1レースでも、全レースでも参加できます。</p></section>"
        "<section class='card'><h2>順位の決まり方</h2>"
        "<p>順位は<b>回収率</b>で決まります。その月に選んだ◎の単勝を、1レース100円ずつ買ったとして計算します。</p>"
        "<div class='scroll'><table><thead><tr><th>例</th><th>選んだレース</th><th>的中</th><th>払戻の合計</th><th>回収率</th></tr></thead><tbody>"
        "<tr><td>Aさん</td><td>10レース（1,000円）</td><td>3回（単勝2.1倍・3.4倍・1.8倍）</td><td>730円</td><td>73.0%</td></tr>"
        "<tr><td>Bさん</td><td>10レース（1,000円）</td><td>1回（単勝15.2倍）</td><td>1,520円</td><td>152.0%</td></tr>"
        "</tbody></table></div>"
        "<p>当てた回数が少なくても、人気の無い馬を当てたBさんのほうが上になります。AIと同じ人気馬ばかり選ぶと、回収率はAIに近づきます。</p>"
        "<p class='meta'>回収率が同じときは、的中数、レース数の多い人が上。すべて同じなら同じ順位です。</p></section>"
        "<section class='card'><h2>AIとの対戦成績</h2>"
        "<p>同じレースで、あなたの◎とAIの◎の<b>着順</b>をくらべます。あなたの◎が先に入れば勝ち、後なら負け、同じ馬を選んだときと同着は引き分けです。</p>"
        "<p>対戦成績は順位には使いませんが、ランキングに「3勝2敗」のような形で並びます。「AIに勝ち越している人が何人いるか」もランキングのページに出ます。</p></section>"
        "<section class='card'><h2>数えないレース</h2><ul>"
        "<li>選んだ馬が出走取消・競走除外になったレース</li><li>払戻の無かったレース（中止など）</li>"
        "<li>AIが「見送り」にしたレースと、予想がまだ出ていないレース（◎を選べません）</li></ul>"
        "<p class='meta'>結果と払戻は、このサイトの成績と同じデータで自動集計します。正式な結果は主催者の発表をご確認ください。</p></section>"
        f"<section class='card'><h2>よくある質問</h2>{faq}</section>"
        "<section class='card'><h2>お願い</h2><ul>"
        "<li>1人1つの名前でお願いします。不適切な名前は運営が削除することがあります。</li>"
        "<li>保存するのは、決めた名前と選んだ◎の記録だけです（<a href='/privacy/'>プライバシーポリシー</a>）。</li>"
        "<li>この企画はゲームです。馬券の購入をすすめるものではなく、的中や利益を約束するものでもありません。馬券は20歳から。</li></ul>"
        "<p><a class='vs-btn' href='/vs/'>ランキングを見る・参加する</a></p></section>")
    return page(f"AI vs あなた 月間ランキングの遊び方｜AIの◎と勝負する無料企画｜{site_name}", body, "/vs/guide/",
                desc="競馬全頭ログのAIの◎と、あなたの◎で勝負する無料の月間ランキングの遊び方。参加のしかた、回収率による順位の決まり方、AIとの対戦成績、よくある質問。",
                head_extra="<link rel='stylesheet' href='/assets/versus.css'>" + jsonld(ld) + jsonld(bc))


def game_data(by_date: dict, race_path, race_label, post_of, horses_of) -> tuple[dict, dict]:
    """API が読む /vsgame/<日付>.json と、月ごとのAIの◎の単勝成績（参考表示用）。

    返り値：({日付: {レースのパス: {post, nums, ai, label[, fin, win]}}}, {"YYYYMM": {n, hits, ret, roi}})
    """
    days: dict = {}
    ai: dict = {}
    for d, ps in by_date.items():
        day = {}
        for p in ps:
            if p.get("confidence") == "見送り":
                continue
            post, nums = post_of(d, p), horses_of(p)
            if not post or not nums:
                continue
            hon = p.get("marks", {}).get("◎")
            rc = {"post": post, "nums": nums, "ai": hon, "label": race_label(p)}
            res = p.get("_result") or {}
            rows = res.get("rows") or []
            if rows:
                rc["fin"] = {str(x.get("number")): str(x.get("finish")) for x in rows if x.get("number") is not None}
                win = []
                for w in (res.get("payouts") or {}).get("単勝") or []:
                    try:
                        win.append([int(str(w.get("combo")).strip()), int(w.get("yen"))])
                    except (TypeError, ValueError):
                        pass
                rc["win"] = win
                # 参考：AIの◎の単勝（取消・除外と払戻なしは数えない。API 側の判定と同じ）
                if hon is not None and win and str(rc["fin"].get(str(hon), "")).isdigit():
                    m = ai.setdefault(d[:6], {"n": 0, "hits": 0, "ret": 0})
                    m["n"] += 1
                    pay = next((y for n, y in win if n == hon), 0)
                    m["ret"] += pay
                    m["hits"] += 1 if pay else 0
            day[race_path(d, p)] = rc
        days[d] = day
    for m in ai.values():
        m["roi"] = round(m["ret"] * 1000 / (m["n"] * 100)) / 10 if m["n"] else 0
    return days, ai


def write_game_data(out_dir, days: dict, ai: dict) -> None:
    g = out_dir / "vsgame"
    g.mkdir(parents=True, exist_ok=True)
    for d, day in days.items():
        (g / f"{d}.json").write_text(json.dumps(day, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for ym, m in ai.items():
        (g / f"ai-{ym}.json").write_text(json.dumps(m, separators=(",", ":")), encoding="utf-8")
