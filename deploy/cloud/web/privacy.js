// Public attribution only. The shell verifies the active frame before calling.
export function placeModelCredit(document, credit) {
  const block=document.getElementById('modelCredit')
  const link=document.getElementById('modelCreditSource')
  const notice=document.getElementById('modelCreditNotice')
  const terms=document.getElementById('modelCreditTerms')
  if (!block || !link) return false
  if (credit === null) {
    block.hidden=true
    link.textContent=''
    link.removeAttribute('href')
    if(notice)notice.textContent=''
    if(terms){terms.hidden=true;terms.removeAttribute('href')}
    return true
  }
  const applicationSources=new Map([
    ["https://github.com/MoFox-Studio/MoFox-ArtCollection", "https://github.com/MoFox-Studio/MoFox-ArtCollection/blob/e59a4305c0ed8a815c8387bd2d25fee633e72dc3/README.md"],
    ["https://github.com/tsunehimatoi/psd2live-examples/tree/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/cases/ds", "https://github.com/tsunehimatoi/psd2live-examples/blob/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/LICENSE"],
    ["https://github.com/tsunehimatoi/psd2live-examples/tree/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/cases/star_lan", "https://github.com/tsunehimatoi/psd2live-examples/blob/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/LICENSE"],
    ["https://github.com/tsunehimatoi/psd2live-examples/tree/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/cases/tml", "https://github.com/tsunehimatoi/psd2live-examples/blob/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/LICENSE"],
    ["https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5", "https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md"],
    ["https://github.com/NOM-Network/Melba-Toaster", "https://github.com/NOM-Network/Melba-Toaster/blob/5760b98f4a601f26b0b00e7ee8b6edab02c1db63/LICENSE-ASSETS.md"],
    ["https://github.com/A8Chann/dsh-pet-live2d", "https://github.com/A8Chann/dsh-pet-live2d/blob/9b7cd8ed0d16bd23fb098bc0c4fdbac63d89de75/NOTICE.md"],

    ["https://github.com/jupiterbjy/Live2DPractice-Cyannyan", "https://github.com/jupiterbjy/Live2DPractice-Cyannyan/blob/898d849e594712cd6afb3bb81c07ecc58c59e024/LICENSE.md"],
    ['https://tyc.rei-yumesaki.net/material/avatar/3d-a/','https://tyc.rei-yumesaki.net/material/avatar/3d-a/'],
    ['https://miko.aituberonair.com/downloads/','https://miko.aituberonair.com/'],
    ['https://github.com/pixiv/three-vrm','https://vrm.dev/en/licenses/1.0/'],
    ['https://github.com/SirRichard94/low-poly-godette','https://github.com/V-Sekai/godot-vrm/blob/e15199f980064028bfa4fbee5e70dddb82dd55c3/vrm_samples/LICENSE_SAMPLES.txt'],
    ['https://github.com/DenpaBorisu/Live2D_Android_Demo/tree/395bcd5b907fd5f1da68992d63f2666a1bea94ca/AndroidSample/Live2dModels/Cat1','https://github.com/DenpaBorisu/Live2D_Android_Demo/blob/395bcd5b907fd5f1da68992d63f2666a1bea94ca/README.md']
,
    ["https://github.com/MjGjVtube/free-filipino-vtuber-template", "https://github.com/MjGjVtube/free-filipino-vtuber-template/blob/e1c70b0c0ccaaf4274bc537384e9341f80046775/LICENSE"],
    ["https://github.com/Ariakage/live2d-agent-kit", "https://github.com/Ariakage/live2d-agent-kit/blob/354d95800b7d498246dfb658e0e2ee379c29caa4/examples/pink-sakura/LICENSE.md"],
    ["https://github.com/yamato3010/live2d-nadeshiko", "https://github.com/yamato3010/live2d-nadeshiko/blob/0a27301bf249c230cd24c697e2fb1f8a3ae59a9b/README.md"],
    ["https://github.com/elainyilanchen/blender-vrm-perfect-sync/tree/d812944595e3ba25cab60649319c79fefac59dc0/samples", "https://github.com/elainyilanchen/blender-vrm-perfect-sync/blob/d812944595e3ba25cab60649319c79fefac59dc0/samples/README.md"],
    ["https://github.com/elainyilanchen/blender-vrm-perfect-sync/tree/d812944595e3ba25cab60649319c79fefac59dc0/samples", "https://github.com/elainyilanchen/blender-vrm-perfect-sync/blob/d812944595e3ba25cab60649319c79fefac59dc0/samples/README.md"],
    ["https://github.com/yuna0x0/AliceChan", "https://github.com/yuna0x0/AliceChan/blob/68850a304e5ae0f7b39fc2d75ed21134e6f5a715/LICENSE.md"],
    ["https://github.com/tegnike/deepseek-chan-vrm", "https://github.com/tegnike/deepseek-chan-vrm/blob/3b28db3bdde8d2e73b698a060044e0d8ebdf8b7b/LICENSE"]
,
    ["https://github.com/xShiroeNguyenx/desktop-companion", "https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md"]
  ])
  if (!credit || typeof credit.name !== 'string' || typeof credit.author !== 'string'
    || !credit.name.trim() || !credit.author.trim() || credit.name.length>500 || credit.author.length>500
    || typeof credit.source !== 'string' || (!/^https:\/\/hub\.vroid\.com\/en\/characters\/[0-9]+\/models\/[0-9]+$/.test(credit.source)
      && !applicationSources.has(credit.source))) return false
  if(applicationSources.has(credit.source) && (credit.terms!==applicationSources.get(credit.source)
    || typeof credit.notice!=='string' || !credit.notice.trim() || credit.notice.length>1000))return false
  link.textContent=`${credit.name} · ${credit.author}`
  link.href=credit.source
  if(notice)notice.textContent=applicationSources.has(credit.source)?credit.notice:''
  if(terms){terms.hidden=!applicationSources.has(credit.source);if(!terms.hidden)terms.href=credit.terms;else terms.removeAttribute('href')}
  block.hidden=false
  return true
}

export function preparePrivacy(document) {
  const panel=document.querySelector('.privacy')
  if (!panel) return
  document.addEventListener('keydown',event=>{
    if (event.key==='Escape' && panel.open) { panel.open=false;panel.querySelector('summary')?.focus() }
  })
  document.addEventListener('pointerdown',event=>{
    if (panel.open && !panel.contains(event.target)) panel.open=false
  })
}
