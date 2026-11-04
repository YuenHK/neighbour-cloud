const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const load=()=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(path.resolve('deploy/cloud/web/privacy.js'))).toString('base64'))
function document(){
 const block={hidden:true},link={textContent:'',href:'',removeAttribute(name){delete this[name]}}
 return {block,link,getElementById:id=>({modelCredit:block,modelCreditSource:link})[id]}
}
test('public attribution moves to its dedicated slot as text and can be cleared without keeping an old source',async()=>{
 const api=await load(),doc=document()
 const row={name:'<img src=x onerror=alert(1)>',author:'Public author',source:'https://hub.vroid.com/en/characters/123/models/456'}
 assert.equal(api.placeModelCredit(doc,row),true)
 assert.equal(doc.link.textContent,row.name+' · Public author');assert.equal(doc.block.hidden,false)
 assert.equal(api.placeModelCredit(doc,null),true)
 assert.equal(doc.block.hidden,true);assert.equal(doc.link.textContent,'');assert.equal(doc.link.href,undefined)
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
