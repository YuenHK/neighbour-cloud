// Public attribution only. The shell verifies the active frame before calling.
export function placeModelCredit(document, credit) {
  const block=document.getElementById('modelCredit')
  const link=document.getElementById('modelCreditSource')
  if (!block || !link) return false
  if (credit === null) {
    block.hidden=true
    link.textContent=''
    link.removeAttribute('href')
    return true
  }
  if (!credit || typeof credit.name !== 'string' || typeof credit.author !== 'string'
    || !credit.name.trim() || !credit.author.trim() || credit.name.length>500 || credit.author.length>500
    || typeof credit.source !== 'string' || !/^https:\/\/hub\.vroid\.com\/en\/characters\/[0-9]+\/models\/[0-9]+$/.test(credit.source)) return false
  link.textContent=`${credit.name} · ${credit.author}`
  link.href=credit.source
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
