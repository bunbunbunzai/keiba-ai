"""全頭ログ オーナーズリーグのページ（厩舎・今週の出走・月間ランキング・規約・管理）。

ページは静的HTMLで、中身は league/ の API（Cloudflare Workers）から読む。
LEAGUE_URL（API のURL）が設定されているときだけ作る。一般公開までは noindex で、ナビ・サイトマップにも載せない。
"""
from __future__ import annotations

TABS = [("/league/", "厩舎"), ("/league/race/", "今週の出走"), ("/league/ranking/", "月間ランキング"), ("/league/rules/", "規約")]


def tabs(cur: str) -> str:
    return ("<nav class='lg-tabs'>" + "".join(f"<a href='{p}'{' aria-current=\"page\"' if p == cur else ''}>{t}</a>" for p, t in TABS)
            + "</nav>")


def head(cur: str, sub: str) -> str:
    return (f"<p class='crumb'><a href='/'>トップ</a> › オーナーズリーグ</p>"
            f"<div class='lg-head'><img src='/assets/zk-normal.png' alt='' width='56' height='56'><div><h1>全頭ログ オーナーズリーグ <span class='lg-beta'>β</span></h1>"
            f"<p class='meta'>{sub}</p></div></div>{tabs(cur)}"
            "<div id='lg-gate' hidden></div>")


RULES = """
<section class='card'><h2>あそびかた</h2><ol class='lg-steps'>
<li><b>厩舎で馬を1頭つくる</b>：馬名と勝負服を決めます。馬と戦績は月をまたいで残ります。</li>
<li><b>毎週1回、調教する</b>：スピード・スタミナ・パワーのどれか1つ。調教した回数がその月のレベルになります。</li>
<li><b>今週の対象レースに出走する</b>：週ごとに2〜3本の実際のレースが対象です。1本を選び、そのレースに出る実在の馬を1頭指名します。あなたの馬の着順は、指名した馬の確定着順と同じになります。</li>
<li><b>月間ランキングで競う</b>：1か月は4節。そのうち得点の高い3節の合計で順位を決めます。</li></ol></section>
<section class='card'><h2>得点</h2>
<table><thead><tr><th>着順</th><th>1着</th><th>2着</th><th>3着</th><th>4着</th><th>5着</th><th>6着以下</th></tr></thead>
<tbody><tr><td>ポイント</td><td>1,000</td><td>600</td><td>400</td><td>250</td><td>150</td><td>0</td></tr></tbody></table>
<p>対象レースにはそれぞれ<b>適性</b>（芝短距離・芝中長距離・ダート）があります。その月に重ねた調教が適性に合っていると、1レベルにつき5%、最大10%のポイントが上乗せされます（芝短距離＝スピード、芝中長距離＝スタミナ、ダート＝パワー）。調教のレベルは月が替わると0に戻ります。</p>
<p class='meta'>実際のレースの賞金やオッズは得点に使いません。ポイントはゲームの中だけのもので、換金・譲渡はできません。</p></section>
<section class='card'><h2>締切と指名</h2><ul>
<li>締切は節ごとに1つで、原則としてその節の対象レースのうち最初のレースの発走時刻です（日本時間）。</li>
<li>締切までは何度でも出走レースと指名馬を変えられます。締切後は変更できません。調教は1節1回で、やり直しはできません。</li>
<li>締切までは、自分の指名は自分にしか見えません。締切後は全員の指名を公開します。</li>
<li>同じ実在馬を何人が指名してもかまいません。</li></ul></section>
<section class='card'><h2>取消・中止・結果の訂正</h2><ul>
<li>締切前に指名した馬が出走取消・除外になったときは、締切までに指名を変えてください。締切後に取消・除外になった場合、その節は0ポイントです。</li>
<li>対象レースが中止になった場合、そのレースを選んだ人はその節0ポイントです（上位3節の合計には、ほかの節が使われます）。</li>
<li>主催者が着順を訂正した場合は、訂正後の着順で計算し直します。同じ結果を何度入れ直しても、得点が二重になることはありません。</li></ul></section>
<section class='card'><h2>順位と同点</h2><ul>
<li>合計ポイントが同じ人は同じ順位です（例：1位が2人なら、その次は3位）。</li>
<li>称号とトロフィー：月間チャンピオン（1位）、月間2位、月間3位。0ポイントの人には付きません。</li></ul></section>
<section class='card' id='prize'><h2>賞品（賞品付きの月だけ）</h2>
<p>賞品付きの月は、優勝にAmazonギフトカード1,000円分、2位・3位に各500円分を贈ります（月間総額2,000円）。賞品付きかどうかは月ごとに、このページと月間ランキングに表示します。β期間中は称号とトロフィーのみで、賞品はありません。</p>
<ul><li><b>同点の場合の按分</b>：同じ順位の人たちが占める順位の枠（例：1位が2人なら1位と2位の枠）の賞品の合計を、その人数で等分します（1円未満は切り捨て）。例：1位が2人なら各750円分、2位が3人なら（500円＋500円）÷3で各333円分。</li>
<li>受賞は、月の締めくくりに運営が結果を確認して承認したときに確定します。不正（複数の厩舎を使った参加など）が見つかった場合は対象外とします。</li>
<li>ギフトカードの購入と送付は運営が手作業で行います。受け取り方法は受賞確定後にご案内します。</li></ul></section>
<section class='card'><h2>参加について</h2><ul>
<li>参加は無料です。馬券の購入、課金、広告やアフィリエイトへの申込みは、参加の条件にも有利な扱いにもなりません。</li>
<li>厩舎の登録情報は、いまお使いのブラウザに保存されます。ほかの端末で遊ぶときは、厩舎ページの「引き継ぎコード」を使ってください。</li>
<li>1人1厩舎でお願いします。馬名が不適切な場合は運営が変更することがあります。</li>
<li>レースの情報と着順は、運営が主催者の発表をもとに登録します。正式な結果は主催者の発表をご確認ください。</li></ul></section>
"""

ADMIN = """
<section class='card'><h2>管理者</h2><p class='meta'>管理用のトークンを入れてください（このブラウザのこのタブを閉じると消えます）。</p>
<div class='pick'><input id='ad-token' type='password' placeholder='管理トークン' autocomplete='off'><button type='button' id='ad-login'>使う</button></div>
<pre id='ad-out' class='lg-pre'></pre></section>
<section class='card'><h2>設定</h2>
<label><input type='checkbox' id='ad-public'> 一般公開（Workers の LEAGUE_PUBLIC=1 も必要）</label><br>
<label><input type='checkbox' id='ad-prizes'> 賞品を使う（Workers の PRIZES_ALLOWED=1 も必要）</label><br>
<button type='button' data-ad='settings'>保存</button></section>
<section class='card'><h2>節</h2><div class='lg-form'>
<input id='ad-r-ym' placeholder='月 2026-12'><input id='ad-r-idx' placeholder='節 1〜4'><input id='ad-r-dl' placeholder='締切 2026-12-07T15:30（空なら最初の発走）'>
<button type='button' data-ad='round'>節を保存</button></div></section>
<section class='card'><h2>対象レース</h2><div class='lg-form'>
<input id='ad-c-round' placeholder='節ID 2026-12-1'><input id='ad-c-id' placeholder='レースID（空なら自動）'><input id='ad-c-label' placeholder='レース名 例：東京11R 〇〇S'>
<input id='ad-c-post' placeholder='発走 2026-12-07T15:40'>
<select id='ad-c-apt'><option value='turf_short'>芝短距離</option><option value='turf_long'>芝中長距離</option><option value='dirt'>ダート</option></select>
<input id='ad-c-site' placeholder='サイトのレースID（全頭診断から移動用・任意）'>
<textarea id='ad-c-field' rows='8' placeholder='出走馬（1行に「馬番 馬名」）&#10;1 〇〇〇〇&#10;2 △△△△'></textarea>
<button type='button' data-ad='race'>レースを保存</button></div></section>
<section class='card'><h2>出走取消・除外</h2><div class='lg-form'>
<input id='ad-s-race' placeholder='レースID'><input id='ad-s-num' placeholder='馬番'>
<button type='button' data-ad='scratch'>取消にする</button><button type='button' data-ad='unscratch'>取消を戻す</button></div></section>
<section class='card'><h2>確定着順（登録・訂正）</h2><div class='lg-form'>
<input id='ad-x-race' placeholder='レースID'>
<textarea id='ad-x-fin' rows='6' placeholder='1行に「馬番 着順」（1〜5着だけでも可）&#10;7 1&#10;3 2&#10;12 3'></textarea>
<button type='button' data-ad='result'>着順を保存（得点を計算し直す）</button><button type='button' data-ad='cancel'>レース中止にする</button></div></section>
<section class='card'><h2>月の確定</h2><div class='lg-form'>
<input id='ad-m-ym' placeholder='月 2026-12'>
<button type='button' data-ad='prize_on'>この月を賞品付きにする</button><button type='button' data-ad='prize_off'>賞品なしにする</button>
<button type='button' data-ad='finalize'>集計して確定</button><button type='button' data-ad='approve'>受賞を承認</button><button type='button' data-ad='reopen'>確定を取り消す</button></div></section>
<section class='card'><h2>現在の状態</h2><button type='button' data-ad='overview'>読み込む</button><div id='ad-ov'></div></section>
"""

CSS = """
.lg-head{display:flex;gap:12px;align-items:center}.lg-head h1{margin:0}.lg-beta{font-size:13px;background:var(--acc);color:#fff;border-radius:6px;padding:2px 7px;vertical-align:middle}
.lg-tabs{display:flex;gap:4px;margin:14px 0 6px;border-bottom:2px solid var(--rule);overflow-x:auto}.lg-tabs a{padding:8px 12px;white-space:nowrap;color:var(--fg);text-decoration:none;font-weight:700;font-size:14px}
.lg-tabs a[aria-current]{background:var(--rule);color:var(--bg);border-radius:8px 8px 0 0}
.lg-card{border:1px solid var(--line);border-radius:14px;background:var(--panel);padding:14px 16px;margin:14px 0}
.lg-horse{display:flex;gap:14px;align-items:center}.lg-horse .nm{font-size:22px;font-weight:800}.lg-silk{flex:none}
.lg-lv{display:grid;grid-template-columns:auto 1fr auto;gap:6px 10px;align-items:center;margin-top:8px}.lg-bar{height:10px;background:var(--line);border-radius:6px;overflow:hidden}.lg-bar i{display:block;height:100%;background:var(--acc)}
.lg-btn,.lg-form button,#lg-app button.go{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer}
.lg-btn[disabled],#lg-app button[disabled]{opacity:.45;cursor:not-allowed}.lg-btn.sub{background:none;color:var(--acc);border:1px solid var(--acc)}
.lg-train{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.lg-train button{padding:12px 6px;border-radius:10px;border:2px solid var(--acc);background:var(--panel);color:var(--fg);font-weight:700;cursor:pointer}
.lg-train button.on{background:var(--acc);color:#fff}.lg-train button.on[disabled]{opacity:1}
.lg-race{border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0;background:var(--panel)}.lg-race.sel{border:2px solid var(--acc)}
.lg-race h3{margin:0 0 4px;font-size:16px}.lg-apt{display:inline-block;font-size:12px;border-radius:6px;padding:1px 8px;background:var(--acc-soft);color:var(--acc);font-weight:700}
.lg-field{list-style:none;padding:0;margin:8px 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:6px}
.lg-field label{display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:7px 8px;cursor:pointer}
.lg-field input:checked+span{font-weight:800;color:var(--acc)}.lg-field .x{opacity:.45;text-decoration:line-through;cursor:not-allowed}
.lg-dl{font-weight:700}.lg-dl.closed{color:var(--hit)}.lg-msg{margin:8px 0;padding:8px 12px;border-radius:8px;background:var(--acc-soft)}.lg-msg.err{background:var(--hit-soft);color:var(--hit)}
.lg-rank,.lg-career{list-style:none;padding:0;margin:10px 0}.lg-rank li,.lg-career li{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
.lg-rank li.me{background:var(--acc-soft)}.lg-rank .rk{width:2.6em;font-size:20px;font-weight:800;text-align:right}.lg-rank .rk small,.lg-rank .tt small,.lg-career .tt small{font-size:11px;font-weight:400;color:var(--mut);margin-left:1px}
.lg-rank .hn,.lg-career li>span:first-child{flex:1;min-width:0}.lg-rank .hn b{word-break:break-all}.lg-rank .hn small,.lg-career small{display:block;color:var(--mut);font-size:12px}
.lg-rank .tt,.lg-career .tt{font-size:18px;font-weight:800;text-align:right;white-space:nowrap}
.lg-trophy{font-size:12px;font-weight:700;border-radius:6px;padding:1px 6px;background:#f2c200;color:#17201b;white-space:nowrap}
.lg-prize{border:2px solid #f2c200;border-radius:12px;padding:10px 14px;margin:10px 0}
.lg-form{display:grid;gap:8px}.lg-card input[type=text]{width:100%;box-sizing:border-box}.lg-horse .lg-form{min-width:0}.lg-form input,.lg-form select,.lg-form textarea,#lg-app input[type=text]{padding:8px;border:1px solid var(--line);border-radius:8px;font:inherit;background:var(--panel);color:var(--fg)}
.lg-swatches{display:flex;gap:6px;flex-wrap:wrap}.lg-swatches button{width:30px;height:30px;border-radius:50%;border:2px solid var(--line);cursor:pointer}.lg-swatches button[aria-pressed=true]{outline:3px solid var(--acc);outline-offset:2px}
.lg-pre{white-space:pre-wrap;font-size:12px;max-height:240px;overflow:auto;background:var(--acc-soft);padding:8px;border-radius:8px}
.lg-steps li{margin:6px 0}
"""

JS = r"""(function(){
var app=document.getElementById('lg-app');if(!app)return;
var API=app.dataset.api, PAGE=app.dataset.page;
var COLORS=["#146b45","#c0122d","#1d4ed8","#f2c200","#ffffff","#17201b","#e8792b","#7c3aed","#ec4899","#0ea5e9"];
var PATTERNS={solid:"無地",stripes:"縦じま",hoops:"横じま",sash:"たすき",stars:"星",halves:"左右2色"};
var STAT={speed:"スピード",stamina:"スタミナ",power:"パワー"},APT={turf_short:"芝短距離",turf_long:"芝中長距離",dirt:"ダート"},APTSTAT={turf_short:"speed",turf_long:"stamina",dirt:"power"};
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v);}catch(e){return null;}}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function api(method,path,body,admin){var h={'content-type':'application/json'};var t=admin?ss('lg_admin'):ls('lg_token');if(t)h.authorization='Bearer '+t;var pv=ls('lg_pv');if(pv)h['x-league-preview']=pv;
 return fetch(API+path,{method:method,headers:h,body:body?JSON.stringify(body):undefined}).then(function(r){return r.json().then(function(j){if(!j.ok){var e=new Error(j.error||'エラー');e.status=r.status;e.preview=j.preview_required;throw e;}return j.data;});});}
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);sessionStorage.setItem(k,v);}catch(e){return null;}}
function msg(el,t,err){el.innerHTML='<p class="lg-msg'+(err?' err':'')+'">'+esc(t)+'</p>';}
function fail(e){if(e.preview){gate();return;}msg(app,e.message,true);}
function gate(){var g=document.getElementById('lg-gate');g.hidden=false;app.innerHTML='';
 g.innerHTML='<div class="lg-card"><p>オーナーズリーグは準備中です。関係者の方はプレビュー用のコードを入れてください。</p><div class="pick"><input type="text" id="pv" placeholder="プレビューコード"> <button class="lg-btn" id="pvb">入る</button></div></div>';
 document.getElementById('pvb').onclick=function(){ls('lg_pv',document.getElementById('pv').value.trim());location.reload();};}
function silk(s,size){s=s||{body:COLORS[0],sleeve:COLORS[4],pattern:'solid'};size=size||56;var b=s.body,a=s.accent||s.sleeve,p='';
 var clip='<clipPath id="c'+size+'"><path d="M22 8 L42 8 L52 14 L60 30 L50 34 L46 26 L46 58 L18 58 L18 26 L14 34 L4 30 L12 14 Z"/></clipPath>';
 if(s.pattern==='stripes')p='<g clip-path="url(#c'+size+')" fill="'+a+'"><rect x="20" y="0" width="5" height="64"/><rect x="30" y="0" width="5" height="64"/><rect x="40" y="0" width="5" height="64"/></g>';
 else if(s.pattern==='hoops')p='<g clip-path="url(#c'+size+')" fill="'+a+'"><rect x="0" y="22" width="64" height="6"/><rect x="0" y="34" width="64" height="6"/><rect x="0" y="46" width="64" height="6"/></g>';
 else if(s.pattern==='sash')p='<g clip-path="url(#c'+size+')"><path d="M18 14 L26 10 L48 58 L40 60 Z" fill="'+a+'"/></g>';
 else if(s.pattern==='stars')p='<g fill="'+a+'"><circle cx="26" cy="30" r="3"/><circle cx="38" cy="30" r="3"/><circle cx="32" cy="42" r="3"/><circle cx="26" cy="52" r="3"/><circle cx="38" cy="52" r="3"/></g>';
 else if(s.pattern==='halves')p='<g clip-path="url(#c'+size+')"><rect x="32" y="0" width="32" height="64" fill="'+a+'"/></g>';
 return '<svg class="lg-silk" width="'+size+'" height="'+size+'" viewBox="0 0 64 64" role="img" aria-label="勝負服"><defs>'+clip+'</defs>'+
 '<path d="M22 8 L42 8 L52 14 L60 30 L50 34 L46 26 L46 58 L18 58 L18 26 L14 34 L4 30 L12 14 Z" fill="'+b+'" stroke="#17201b" stroke-width="2"/>'+
 '<path d="M12 14 L4 30 L14 34 L18 26 Z M52 14 L60 30 L50 34 L46 26 Z" fill="'+s.sleeve+'" stroke="#17201b" stroke-width="2"/>'+p+
 '<path d="M22 8 Q32 16 42 8" fill="none" stroke="#17201b" stroke-width="2"/></svg>';}
function fmtDl(d){if(!d)return '未定';var m=d.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);return +m[2]+'月'+(+m[3])+'日 '+m[4]+':'+m[5];}
function left(d){var t=Date.UTC(+d.slice(0,4),+d.slice(5,7)-1,+d.slice(8,10),+d.slice(11,13)-9,+d.slice(14,16))-Date.now();if(t<=0)return '締め切りました';var h=Math.floor(t/36e5),m=Math.floor(t%36e5/6e4);return 'あと'+(h>=24?Math.floor(h/24)+'日'+(h%24)+'時間':h+'時間'+m+'分');}

// ---------- 厩舎 ----------
function horseForm(h,onSave){var s=h?JSON.parse(JSON.stringify(h.silks)):{body:COLORS[0],sleeve:COLORS[4],pattern:'stripes',accent:COLORS[4]};
 var w=document.createElement('div');w.className='lg-card';
 function sw(key){return '<div class="lg-swatches" data-k="'+key+'">'+COLORS.map(function(c){return '<button type="button" style="background:'+c+'" aria-label="'+c+'" aria-pressed="'+(s[key]===c)+'" data-c="'+c+'"></button>';}).join('')+'</div>';}
 w.innerHTML='<h2>'+(h?'馬名・勝負服を変える':'馬をつくる')+'</h2><div class="lg-horse"><span id="pvw">'+silk(s,80)+'</span><div class="lg-form" style="flex:1">'+
 '<label>馬名（2〜12文字）<br><input type="text" id="hn" maxlength="12" value="'+esc(h?h.name:'')+'" placeholder="例：ゼントウボーイ"></label></div></div>'+
 '<p>胴の色</p>'+sw('body')+'<p>袖の色</p>'+sw('sleeve')+'<p>柄の色</p>'+sw('accent')+
 '<p>柄</p><select id="hp">'+Object.keys(PATTERNS).map(function(k){return '<option value="'+k+'"'+(s.pattern===k?' selected':'')+'>'+PATTERNS[k]+'</option>';}).join('')+'</select>'+
 '<p><button class="lg-btn" id="hs">'+(h?'保存する':'この馬で厩舎をつくる')+'</button></p><div id="hm"></div>';
 w.addEventListener('click',function(e){var b=e.target.closest('.lg-swatches button');if(!b)return;var k=b.parentNode.dataset.k;s[k]=b.dataset.c;b.parentNode.querySelectorAll('button').forEach(function(x){x.setAttribute('aria-pressed',x===b);});w.querySelector('#pvw').innerHTML=silk(s,80);});
 w.querySelector('#hp').onchange=function(){s.pattern=this.value;w.querySelector('#pvw').innerHTML=silk(s,80);};
 w.querySelector('#hs').onclick=function(){var btn=this;btn.disabled=true;var go=function(){return api('POST','/api/horse',{name:w.querySelector('#hn').value,silks:s});};
  (ls('lg_token')?go():api('POST','/api/register').then(function(r){ls('lg_token',r.token);return go();})).then(function(){onSave();}).catch(function(e){btn.disabled=false;if(e.preview)return gate();msg(w.querySelector('#hm'),e.message,true);});};
 return w;}
function stable(){api('GET','/api/me').then(function(me){if(!me.horse){app.innerHTML='';app.appendChild(intro());app.appendChild(horseForm(null,stable));return;}
 var h=me.horse,lv=me.levels||{speed:0,stamina:0,power:0};
 var html='<div class="lg-card lg-horse">'+silk(h.silks,84)+'<div><div class="nm">'+esc(h.name)+'</div><div class="meta">厩舎開業 '+esc(h.created_at.slice(0,10))+'</div></div></div>';
 html+='<div class="lg-card"><h2>今月の調教レベル</h2><div class="lg-lv">'+['speed','stamina','power'].map(function(k){var b=Math.min(lv[k]*5,10);return '<b>'+STAT[k]+'</b><div class="lg-bar"><i style="width:'+Math.min(lv[k]/2*100,100)+'%"></i></div><span>Lv'+lv[k]+'（加点'+b+'%）</span>';}).join('')+'</div>'+
  '<p class="meta">芝短距離＝スピード、芝中長距離＝スタミナ、ダート＝パワー。1レベル5%・最大10%。月が替わると0に戻ります。</p><p><a class="lg-btn" href="/league/race/">今週の出走へ</a></p></div>';
 var c=me.career||{rounds:[],months:[]};
 html+='<div class="lg-card"><h2>戦績</h2>'+(c.rounds.length?'<ul class="lg-career">'+c.rounds.map(function(r){return '<li><span><b>'+esc(r.title)+'</b>　'+esc(r.race_label)+'<br><small>'+r.number+'番を指名・'+esc(r.finish?r.finish+(/^\d+$/.test(r.finish)?'着':''):(r.note||'-'))+'</small></span><span class="tt">'+r.points.toLocaleString()+'<small>pt</small>'+(r.bonus_pct?'<br><small>+'+r.bonus_pct+'%</small>':'')+'</span></li>';}).join('')+'</ul>':'<p>まだ出走していません。</p>')+
  (c.months.length?'<h3>過去の月</h3><ul>'+c.months.map(function(m){return '<li>'+esc(m.ym)+'：'+m.rank+'位（'+m.total.toLocaleString()+'ポイント）'+(m.title?' <span class="lg-trophy">🏆 '+esc(m.title)+'</span>':'')+'</li>';}).join('')+'</ul>':'')+'</div>';
 html+='<details class="lg-card"><summary>ほかの端末で遊ぶ（引き継ぎコード）</summary><p>このコードを、ほかの端末の厩舎ページで入れると同じ厩舎を使えます。人に教えないでください。</p><input type="text" readonly value="'+esc(ls('lg_token'))+'" style="width:100%" onclick="this.select()"></details>';
 app.innerHTML=html;var f=horseForm(h,stable);var d=document.createElement('details');d.className='lg-card';d.innerHTML='<summary>馬名・勝負服を変える</summary>';d.appendChild(f);f.className='';app.appendChild(d);
}).catch(function(e){if(e.status===401){ls('lg_token',null);app.innerHTML='';app.appendChild(intro());app.appendChild(horseForm(null,stable));return;}fail(e);});}
function intro(){var d=document.createElement('div');d.innerHTML='<div class="lg-card"><p>実際のレースに出る馬を1頭指名して、あなたの仮想馬を走らせるゲームです。指名した馬の着順が、そのままあなたの馬の着順になります。毎週の調教と出走で、月間ランキングの上位を目指しましょう。<a href="/league/rules/">あそびかた・規約</a></p></div>'+
 '<details class="lg-card"><summary>引き継ぎコードを持っている</summary><div class="pick"><input type="text" id="rc" placeholder="引き継ぎコード"> <button class="lg-btn" id="rcb">使う</button></div></details>';
 setTimeout(function(){var b=document.getElementById('rcb');if(b)b.onclick=function(){ls('lg_token',document.getElementById('rc').value.trim());stable();};});return d;}

// ---------- 今週の出走 ----------
function race(){var q=new URLSearchParams(location.search);api('GET','/api/round'+(q.get('round')?'?round_id='+encodeURIComponent(q.get('round')):'')).then(function(v){
 if(!v.round){app.innerHTML='<div class="lg-card"><p>今週の対象レースはまだ発表されていません。</p></div>';return;}
 var r=v.round,closed=r.closed,mine=v.my_entry,me=!!ls('lg_token');var lv=v.levels||{speed:0,stamina:0,power:0};
 var want=q.get('site_race');var html='<div class="lg-card"><h2>'+esc(r.title)+'</h2><p>締切：<span class="lg-dl'+(closed?' closed':'')+'">'+fmtDl(r.deadline)+'（'+(closed?'締め切りました':left(r.deadline))+'）</span></p>'+
  (closed?'':'<p class="meta">締切まで何度でも変えられます。いまの出走登録：'+(v.entry_count||0)+'頭</p>')+'</div>';
 if(!me){html+='<div class="lg-card"><p>出走するには、先に<a href="/league/">厩舎で馬をつくってください</a>。</p></div>';}
 else{var tr=v.my_training&&v.my_training.stat;
  html+='<div class="lg-card"><h2>今週の調教（1回）</h2><div class="lg-train">'+['speed','stamina','power'].map(function(k){return '<button type="button" data-train="'+k+'"'+(tr===k?' class="on"':'')+(tr||closed?' disabled':'')+'>'+STAT[k]+'<br><small>Lv'+lv[k]+'</small></button>';}).join('')+'</div>'+
  '<p class="meta">'+(tr?'今週は「'+STAT[tr]+'」を調教しました。':closed?'締め切りました。':'どれか1つを選ぶと、その月のレベルが1上がります（やり直しはできません）。')+'</p><div id="trm"></div></div>';
  if(mine)html+='<div class="lg-card"><b>あなたの出走：</b>'+esc(mine.race_label)+'　'+mine.number+'番 '+esc(mine.horse_name)+(v.my_score?'　→ <b>'+(v.my_score.finish?esc(v.my_score.finish)+'着':esc(v.my_score.note||''))+'・'+v.my_score.points.toLocaleString()+'ポイント</b>':'')+'</div>';}
 r.races.forEach(function(rc){var st=APTSTAT[rc.aptitude],b=Math.min(lv[st]*5,10),sel=mine&&mine.race_id===rc.id||(!mine&&want&&rc.site_race_id===want);
  html+='<div class="lg-race'+(sel?' sel':'')+'" data-race="'+esc(rc.id)+'"><h3>'+esc(rc.label)+'</h3><p class="meta">'+fmtDl(rc.post)+'発走　<span class="lg-apt">'+APT[rc.aptitude]+'</span>　'+(me?'あなたの加点：'+STAT[st]+'Lv'+lv[st]+' → +'+b+'%':'')+(rc.status==='cancelled'?'　<b>中止</b>':'')+(rc.article_url?'　<a href="'+esc(rc.article_url)+'">全頭診断を読む</a>':'')+'</p>'+
  '<ul class="lg-field">'+rc.field.map(function(h){var chk=mine&&mine.race_id===rc.id&&mine.number===h.number;var fin=rc.result&&rc.result[h.number];
   return '<li><label class="'+(h.scratched?'x':'')+'"><input type="radio" name="pick" value="'+esc(rc.id)+':'+h.number+'"'+(chk?' checked':'')+(h.scratched||closed||!me||rc.status==='cancelled'?' disabled':'')+'><span>'+h.number+' '+esc(h.name)+(h.scratched?'（取消）':'')+(fin?' <b>'+esc(fin)+(/^\d+$/.test(fin)?'着':'')+'</b>':'')+'</span></label></li>';}).join('')+'</ul></div>';});
 if(me&&!closed)html+='<p><button class="lg-btn" id="enter">この馬で出走する</button></p><div id="enm"></div>';
 if(closed&&v.entries)html+='<div class="lg-card"><h2>みんなの出走</h2><div class="scroll"><table><thead><tr><th>馬</th><th>レース</th><th>指名</th><th>着順</th><th>ポイント</th></tr></thead><tbody>'+v.entries.map(function(e){var rc=r.races.filter(function(x){return x.id===e.race_id;})[0];return '<tr><td>'+esc(e.horse)+'</td><td>'+esc(rc?rc.label:'')+'</td><td>'+e.number+'番</td><td>'+esc(e.finish||e.note||'-')+'</td><td>'+(e.points==null?'-':e.points.toLocaleString())+'</td></tr>';}).join('')+'</tbody></table></div></div>';
 app.innerHTML=html;
 app.querySelectorAll('[data-train]').forEach(function(b){b.onclick=function(){if(!confirm(STAT[b.dataset.train]+'を調教します。今週はやり直しできません。よろしいですか？'))return;api('POST','/api/train',{round_id:r.id,stat:b.dataset.train}).then(race).catch(function(e){msg(document.getElementById('trm'),e.message,true);});};});
 var en=document.getElementById('enter');if(en)en.onclick=function(){var p=app.querySelector('input[name=pick]:checked');if(!p){msg(document.getElementById('enm'),'指名する馬を選んでください。',true);return;}var x=p.value.split(':');
  api('POST','/api/enter',{round_id:r.id,race_id:x[0],number:+x[1]}).then(function(){race();}).catch(function(e){msg(document.getElementById('enm'),e.message,true);});};
 app.querySelectorAll('input[name=pick]').forEach(function(i){i.onchange=function(){app.querySelectorAll('.lg-race').forEach(function(d){d.classList.toggle('sel',d.contains(i));});};});
 var s=app.querySelector('.lg-race.sel');if(s&&want)s.scrollIntoView({block:'center'});
}).catch(fail);}

// ---------- 月間ランキング ----------
function ranking(ym){api('GET','/api/ranking'+(ym?'?ym='+ym:'')).then(function(v){
 var opts=(v.months||[]).map(function(m){return '<option value="'+m.ym+'"'+(m.ym===v.ym?' selected':'')+'>'+m.ym.replace('-','年')+'月'+(m.status==='finalized'?'（確定）':'（集計中）')+'</option>';}).join('');
 var html='<div class="lg-card"><label>月 <select id="ym">'+(opts||'<option>'+v.ym+'</option>')+'</select></label> '+(v.status==='finalized'?(v.approved?'<b>確定・受賞承認済み</b>':'<b>確定</b>（受賞は運営の確認待ち）'):'<span class="meta">集計中（4節のうち上位3節の合計）</span>')+'</div>';
 if(v.prizes)html+='<div class="lg-prize"><b>この月は賞品付き</b>：優勝 Amazonギフトカード1,000円分、2位・3位 各500円分（同点は<a href="/league/rules/#prize">規約</a>のとおり按分）。受賞は運営の承認で確定します。</div>';
 else html+='<p class="meta">この月は称号とトロフィーのみです（賞品なし）。</p>';
 if(!v.rows.length)html+='<div class="lg-card"><p>まだ得点がありません。</p></div>';
 else html+='<ol class="lg-rank">'+v.rows.map(function(r){
  return '<li'+(v.me&&r.user_id===v.me?' class="me"':'')+'><span class="rk">'+r.rank+'<small>位</small></span>'+silk(r.silks,34)+'<span class="hn"><b>'+esc(r.horse)+'</b>'+(r.title?' <span class="lg-trophy">🏆 '+esc(r.title)+'</span>':'')+
  '<small>上位3節：'+r.best.map(function(x){return x.points.toLocaleString();}).join(' / ')+(v.prizes&&r.prize_yen?'　賞品 '+r.prize_yen.toLocaleString()+'円分':'')+'</small></span><span class="tt">'+r.total.toLocaleString()+'<small>pt</small></span></li>';}).join('')+'</ol>';
 app.innerHTML=html;document.getElementById('ym').onchange=function(){ranking(this.value);};
}).catch(fail);}

// ---------- 管理 ----------
function admin(){var out=document.getElementById('ad-out');var t=document.getElementById('ad-token');t.value=ss('lg_admin')||'';
 document.getElementById('ad-login').onclick=function(){ss('lg_admin',t.value.trim());ov();};
 function v(id){return (document.getElementById(id).value||'').trim();}
 function show(p){p.then(function(d){out.textContent=JSON.stringify(d,null,1).slice(0,3000);ov();}).catch(function(e){out.textContent='エラー：'+e.message;});}
 function lines(id){return v(id).split(/\n/).map(function(l){return l.trim().split(/\s+/);}).filter(function(a){return a[0];});}
 function ov(){api('GET','/api/admin/overview',null,true).then(function(o){document.getElementById('ad-public').checked=o.settings.public==='1';document.getElementById('ad-prizes').checked=o.settings.prizes_allowed==='1';
  document.getElementById('ad-ov').innerHTML='<p>厩舎 '+o.horses+'／登録 '+o.users+'　公開:'+(o.flags.public?'ON':'OFF')+'　賞品:'+(o.flags.prizes_allowed?'ON':'OFF')+'</p><ul>'+o.rounds.map(function(r){return '<li><b>'+esc(r.id)+'</b> '+esc(r.title)+' 締切'+esc(r.deadline||'未定')+(r.closed?'（締切済）':'')+'<ul>'+r.races.map(function(c){return '<li>'+esc(c.id)+' '+esc(c.label)+' '+APT[c.aptitude]+' '+c.status+(c.result?' 結果v'+c.result_version:'')+'</li>';}).join('')+'</ul></li>';}).join('')+'</ul>'+
  '<p>月：'+o.months.map(function(m){return esc(m.ym)+'('+m.status+(m.approved?'・承認':'')+(m.prize_enabled?'・賞品':'')+')';}).join('、')+'</p>';}).catch(function(e){out.textContent='エラー：'+e.message;});}
 var A={settings:function(){return api('POST','/api/admin/settings',{public:document.getElementById('ad-public').checked,prizes_allowed:document.getElementById('ad-prizes').checked},true);},
  round:function(){return api('POST','/api/admin/round',{ym:v('ad-r-ym'),idx:v('ad-r-idx'),deadline:v('ad-r-dl')||null},true);},
  race:function(){return api('POST','/api/admin/race',{round_id:v('ad-c-round'),id:v('ad-c-id')||undefined,label:v('ad-c-label'),post:v('ad-c-post'),aptitude:v('ad-c-apt'),site_race_id:v('ad-c-site')||null,field:lines('ad-c-field').map(function(a){return {number:a[0],name:a.slice(1).join(' ')};})},true);},
  scratch:function(){return api('POST','/api/admin/scratch',{race_id:v('ad-s-race'),number:v('ad-s-num')},true);},
  unscratch:function(){return api('POST','/api/admin/scratch',{race_id:v('ad-s-race'),number:v('ad-s-num'),scratched:false},true);},
  result:function(){var f={};lines('ad-x-fin').forEach(function(a){f[a[0]]=a[1];});return api('POST','/api/admin/result',{race_id:v('ad-x-race'),status:'final',finishes:f},true);},
  cancel:function(){if(!confirm('レース中止にします。'))return Promise.reject(new Error('取りやめ'));return api('POST','/api/admin/result',{race_id:v('ad-x-race'),status:'cancelled'},true);},
  prize_on:function(){return api('POST','/api/admin/month_prize',{ym:v('ad-m-ym'),on:true},true);},prize_off:function(){return api('POST','/api/admin/month_prize',{ym:v('ad-m-ym'),on:false},true);},
  finalize:function(){return api('POST','/api/admin/finalize',{ym:v('ad-m-ym')},true);},approve:function(){return api('POST','/api/admin/approve',{ym:v('ad-m-ym')},true);},
  reopen:function(){return api('POST','/api/admin/reopen',{ym:v('ad-m-ym')},true);},overview:function(){return api('GET','/api/admin/overview',null,true);}};
 document.querySelectorAll('[data-ad]').forEach(function(b){b.onclick=function(){show(A[b.dataset.ad]());};});
 if(ss('lg_admin'))ov();}

({stable:stable,race:race,ranking:function(){ranking();},admin:admin,rules:function(){}})[PAGE]();
})();"""


def build(write, page, out_dir, api_url: str, site_name: str) -> None:
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "assets" / "league.js").write_text(JS, encoding="utf-8")
    (out_dir / "assets" / "league.css").write_text(CSS, encoding="utf-8")
    extra = "<link rel='stylesheet' href='/assets/league.css'>"
    foot = "<script src='/assets/league.js' defer></script>"

    def app(pg: str, loading: bool = True) -> str:
        return f"<div id='lg-app' data-api='{api_url}' data-page='{pg}'>{'<p class=meta>読み込み中…</p>' if loading else ''}</div>{foot}"

    write("/league/", page(f"厩舎｜オーナーズリーグ｜{site_name}",
                           head("/league/", "実際のレースに出る馬を指名して、あなたの馬を走らせる月間リーグ（無料）") + app("stable"),
                           "/league/", noindex=True, head_extra=extra))
    write("/league/race/", page(f"今週の出走｜オーナーズリーグ｜{site_name}",
                                head("/league/race/", "週に1回の調教と、対象レースへの出走") + app("race"), "/league/race/", noindex=True, head_extra=extra))
    write("/league/ranking/", page(f"月間ランキング｜オーナーズリーグ｜{site_name}",
                                   head("/league/ranking/", "4節のうち上位3節の合計で競います") + app("ranking"), "/league/ranking/", noindex=True, head_extra=extra))
    write("/league/rules/", page(f"規約・あそびかた｜オーナーズリーグ｜{site_name}",
                                 head("/league/rules/", "あそびかた・得点・締切・賞品のルール") + RULES, "/league/rules/", noindex=True, head_extra=extra))
    write("/league/admin/", page(f"管理｜オーナーズリーグ｜{site_name}",
                                 head("", "管理者用") + ADMIN + app("admin", False), "/league/admin/", noindex=True, head_extra=extra))


def article_link(site_race_id: str) -> str:
    """全頭診断の記事から出走画面へ。対象レースに選ばれていれば、そのレースが選ばれた状態で開く。"""
    return (f"<section class='card'><h2>オーナーズリーグ</h2><p>このレースがオーナーズリーグの今週の対象レースなら、ここから出走できます。"
            f"<a class='btn' href='/league/race/?site_race={site_race_id}'>出走画面へ</a></p></section>")
