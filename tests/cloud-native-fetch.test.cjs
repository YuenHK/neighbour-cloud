const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs')
const load=()=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('airi_overlay/cloud-native-fetch.js','utf8')).toString('base64'))
const voiceBody={model:'azure-hiumaan-f0',voice:'zh-HK-HiuMaanNeural',input:'公開測試'}
test('native AIRI manual speech preview uses session PCM, respects draft style, creates WAV without audio playback',async()=>{
 const {managedNativeFetch}=await load(),calls=[]
 const transport={fetch:async(path,init)=>{calls.push({path,body:JSON.parse(init.body),headers:new Headers(init.headers)});return new Response('data: {"audio":"AAAAAA=="}\n\ndata: {"done":true}\n\n')}}
 const request=managedNativeFetch('speech',{transport,speech:()=>({rate:.9,pitch:2,volume:0})})
 const r=await request('https://must-not-be-fetched.invalid',{body:JSON.stringify(voiceBody),headers:{Authorization:'must-not-forward'}})
 const b=new Uint8Array(await r.arrayBuffer())
 assert.equal(new TextDecoder().decode(b.slice(0,4)),'RIFF')
 assert.equal(new DataView(b.buffer).getUint32(24,true),24000)
 assert.equal(calls[0].path,'/_audio/v1/audio/resident-stream')
 assert.deepEqual(calls[0].body.preview,{rate:.9,pitch:2,volume:0})
 assert.equal(calls[0].headers.has('authorization'),false)
 assert.equal(calls.length,1)
 await assert.rejects(request('',{body:JSON.stringify({...voiceBody,voice:'other'})}))
 assert.equal(calls.length,1)
})
test('truncated or failed PCM never yields a playable preview and does not replay synthesis',async()=>{
 const {previewWav}=await load()
 for(const body of ['data: {"audio":"AAAAAA=="}\n\n','data: {"error":"busy"}\n\n'])
  await assert.rejects(previewWav(new Response(body)))
})
test('configured native model adapter only sends the existing Gemma request to same-origin transport',async()=>{
 const {managedNativeFetch}=await load(),calls=[]
 const request=managedNativeFetch('chat',{transport:{fetch:async(p,init)=>{calls.push({p,init});return new Response('{}')}}})
 await request('https://not-used.invalid',{body:JSON.stringify({model:'gemma-4-26b-a4b-it',messages:[]})})
 assert.equal(calls[0].p,'/api/v1/resident/model/v1/chat/completions')
 await assert.rejects(request('',{body:JSON.stringify({model:'paid'})}))
 assert.equal(calls.length,1)
})
test('native hearing adapter reuses bounded WAV transcription with no microphone or external endpoint',async()=>{
 const {managedNativeFetch,pcmWav}=await load(),calls=[]
 const request=managedNativeFetch('hearing',{transcribe:async(audio)=>{calls.push(audio);return '你好'}})
 const body=new FormData();body.set('file',new Blob([pcmWav(new Uint8Array(8000),16000)],{type:'audio/wav'}),'public.wav')
 const r=await request('',{body})
 assert.deepEqual(await r.json(),{text:'你好'});assert.equal(calls.length,1)
})
