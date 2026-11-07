const test = require('node:test'), assert = require('node:assert/strict'), path = require('node:path'), { pathToFileURL } = require('node:url')
const load = () => import(pathToFileURL(path.resolve('airi_overlay/resident-display.js')).href)

test('resident framing follows available orientation and size, including portrait tablets and wide LED strips', async () => {
  const { residentViewportMode } = await load()
  for (const [w, h, mode] of [[256,768,'portrait'],[192,640,'portrait'],[128,384,'portrait'],[390,844,'portrait'],[768,1024,'portrait'],[1024,1366,'portrait'],[1080,1920,'portrait'],[768,256,'compact-landscape'],[844,390,'compact-landscape'],[1920,320,'compact-landscape'],[1280,720,'desktop'],[1920,1080,'desktop'],[3840,2160,'desktop'],[0,768,'desktop'],[NaN,768,'desktop']])
    assert.equal(residentViewportMode(w,h), mode, `${w}x${h}`)
})

test('responsive upper-body close-up is larger than whole-body fit and preserves staff and saved model data', async () => {
  const prior = { document: global.document, innerWidth: global.innerWidth, innerHeight: global.innerHeight }
  try {
    const display = await load(), { galleryFraming } = await import(pathToFileURL(path.resolve('airi_overlay/gallery-fit.js')).href)
    const model={internalModel:{width:1000,height:2000,settings:{json:{}},coreModel:{getDrawableCount:()=>1,getDrawableOpacity:()=>1},getDrawableVertices:()=>[0,0,1000,2000],localTransform:{apply:p=>p}}}
    const fallback=Object.freeze({scale:9,x:400,y:-200})
    global.document={body:{dataset:{cloudView:'resident'}}}
    for (const [width,height] of [[256,768],[390,844],[768,1024],[1024,1366],[768,256]]) {
      global.innerWidth=width; global.innerHeight=height
      assert.equal(display.isAdaptiveResident(),true)
      const fit=galleryFraming(model,{width:width*.9,height:height*.9},fallback,'original-user-model')
      assert.notEqual(fit,fallback)
      const fullScale=Math.min(width*.9/1000,height*.9/2000)*.86
      assert.ok(fit.scale>fullScale*1.5,`${width}x${height} must visibly enlarge the torso`)
      const top=fit.y-1000*fit.scale
      assert.ok(Math.abs(top-height*.9*.04)<1e-8,'head starts near the upper edge')
      assert.ok(top+1200*fit.scale<=height*.9*.9,'head-to-waist region fits within the viewport')
      assert.deepEqual(model.internalModel.settings.json,{})
    }
    global.document.body.dataset.cloudView='settings'
    assert.equal(display.isAdaptiveResident(),false)
    assert.equal(galleryFraming(model,{width:300,height:400},fallback,'original-user-model'),fallback)
    global.document.body.dataset.cloudView='resident';global.innerWidth=1280;global.innerHeight=720
    assert.equal(display.isAdaptiveResident(),false)
    assert.equal(galleryFraming(model,{width:700,height:600},fallback,'original-user-model'),fallback)
  } finally { Object.assign(global,prior) }
})

test('upper-body projection rejects invalid dimensions and remains finite for narrow LED and wide strips', async () => {
  const {upperBodyFraming}=await load()
  for(const viewport of [{width:128,height:384},{width:256,height:768},{width:1920,height:320}]){
    const fit=upperBodyFraming({left:-50,right:50,top:-100,bottom:100},viewport)
    assert.ok(Object.values(fit).every(Number.isFinite))
    assert.ok(Math.abs(-100*fit.scale+fit.y-viewport.height*.04)<1e-8)
    assert.ok(64*fit.scale<=viewport.width)
    assert.ok(120*fit.scale<viewport.height*.9)
  }
  assert.equal(upperBodyFraming({left:1,right:1,top:0,bottom:2},{width:256,height:768}),undefined)
  assert.equal(upperBodyFraming({left:0,right:1,top:0,bottom:2},{width:0,height:768}),undefined)
})
