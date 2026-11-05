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
    ['https://tyc.rei-yumesaki.net/material/avatar/3d-a/','https://tyc.rei-yumesaki.net/material/avatar/3d-a/'],
    ['https://miko.aituberonair.com/downloads/','https://miko.aituberonair.com/'],
    ['https://github.com/pixiv/three-vrm','https://vrm.dev/en/licenses/1.0/'],
    ['https://github.com/SirRichard94/low-poly-godette','https://github.com/V-Sekai/godot-vrm/blob/e15199f980064028bfa4fbee5e70dddb82dd55c3/vrm_samples/LICENSE_SAMPLES.txt'],
    ['https://github.com/DenpaBorisu/Live2D_Android_Demo/tree/395bcd5b907fd5f1da68992d63f2666a1bea94ca/AndroidSample/Live2dModels/Cat1','https://github.com/DenpaBorisu/Live2D_Android_Demo/blob/395bcd5b907fd5f1da68992d63f2666a1bea94ca/README.md']
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
