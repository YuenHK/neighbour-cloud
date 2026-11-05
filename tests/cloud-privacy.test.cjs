const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const load=()=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(path.resolve('deploy/cloud/web/privacy.js'))).toString('base64'))
function document(){
 const block={hidden:true},link={textContent:'',href:'',removeAttribute(name){delete this[name]}},notice={textContent:''},terms={hidden:true,removeAttribute(name){delete this[name]}}
 return {block,link,notice,terms,getElementById:id=>({modelCredit:block,modelCreditSource:link,modelCreditNotice:notice,modelCreditTerms:terms})[id]}
}
test('public attribution moves to its dedicated slot as text and can be cleared without keeping an old source',async()=>{
 const api=await load(),doc=document()
 const row={name:'<img src=x onerror=alert(1)>',author:'Public author',source:'https://hub.vroid.com/en/characters/123/models/456'}
 assert.equal(api.placeModelCredit(doc,row),true)
 assert.equal(doc.link.textContent,row.name+' · Public author');assert.equal(doc.block.hidden,false)
 assert.equal(api.placeModelCredit(doc,null),true)
 assert.equal(doc.block.hidden,true);assert.equal(doc.link.textContent,'');assert.equal(doc.link.href,undefined)
})

test('reviewed application inclusion keeps the author notice and exact original terms as text',async()=>{
 const api=await load(),doc=document()
 const row={name:'Miko',author:'Original author',source:'https://miko.aituberonair.com/downloads/',terms:'https://miko.aituberonair.com/',notice:'Only part of Neighbour; <script>not HTML</script>'}
 assert.equal(api.placeModelCredit(doc,row),true)
 assert.equal(doc.notice.textContent,row.notice);assert.equal(doc.terms.href,row.terms);assert.equal(doc.terms.hidden,false)
 for(const value of [{...row,terms:'https://evil.invalid/'},{...row,notice:''},{...row,notice:'x'.repeat(1001)},{...row,source:'https://miko.aituberonair.com/downloads/?token=private'}])assert.equal(api.placeModelCredit(doc,value),false)
 assert.equal(api.placeModelCredit(doc,null),true)
 assert.equal(doc.notice.textContent,'');assert.equal(doc.terms.hidden,true);assert.equal(doc.terms.href,undefined)
})
test('unsafe or malformed source metadata cannot replace an already valid credit',async()=>{
 const api=await load(),doc=document(),good={name:'Public character',author:'Author',source:'https://hub.vroid.com/en/characters/123/models/456'}
 api.placeModelCredit(doc,good)
 for(const source of ['javascript:alert(1)','http://hub.vroid.com/en/characters/1/models/2','https://hub.vroid.com.evil.test/en/characters/1/models/2','https://user:secret@hub.vroid.com/en/characters/1/models/2','https://hub.vroid.com/en/characters/1/models/2?token=private'])
  assert.equal(api.placeModelCredit(doc,{...good,source}),false)
 for(const value of [{...good,name:'x'.repeat(501)},{...good,author:''},{...good,source:null},{name:'missing'},undefined])
  assert.equal(api.placeModelCredit(doc,value),false)
 assert.equal(doc.link.href,good.source);assert.equal(doc.link.textContent,'Public character · Author')
})

test('original Cat1 and Godette shared models keep exact author terms without allowing arbitrary GitHub links',async()=>{
 const api=await load(),doc=document()
 const cat={name:'Cat1',author:'Boris González / DenpaBorisu',source:'https://github.com/DenpaBorisu/Live2D_Android_Demo/tree/395bcd5b907fd5f1da68992d63f2666a1bea94ca/AndroidSample/Live2dModels/Cat1',terms:'https://github.com/DenpaBorisu/Live2D_Android_Demo/blob/395bcd5b907fd5f1da68992d63f2666a1bea94ca/README.md',notice:'Original public-domain cat artwork; framing only.'}
 const godette={name:'Godette',author:'SirRichard94; VRM adaptation Lyuma; CC BY 3.0',source:'https://github.com/SirRichard94/low-poly-godette',terms:'https://github.com/V-Sekai/godot-vrm/blob/e15199f980064028bfa4fbee5e70dddb82dd55c3/vrm_samples/LICENSE_SAMPLES.txt',notice:'Original and adaptation attribution retained.'}
 for(const row of [cat,godette]){
  assert.equal(api.placeModelCredit(doc,row),true)
  assert.equal(doc.link.textContent,row.name+' · '+row.author)
  assert.equal(doc.notice.textContent,row.notice);assert.equal(doc.terms.href,row.terms)
  for(const changed of [{...row,terms:'https://github.com/unreviewed/LICENSE'},{...row,source:row.source+'?redirect=1'},{...row,source:row.source.replace('github.com','github.com.evil.test')}])assert.equal(api.placeModelCredit(doc,changed),false)
 }
 assert.equal(api.placeModelCredit(doc,{...cat,source:'https://github.com/unreviewed/model'}),false)
})
