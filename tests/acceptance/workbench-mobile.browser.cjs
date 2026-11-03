// Keep all isolated browser regressions mandatory under the existing five checks.
const {spawnSync}=require('node:child_process')
for(const script of ['tests/acceptance/staff-pwa.browser.cjs','tests/acceptance/staff-push-dedup.browser.cjs','tests/cloud-origin.browser.cjs',
 'tests/workbench-filters.browser.cjs','tests/patrol-workflow.browser.cjs','tests/resident-pcm-native.browser.cjs',
 'tests/background-pattern.browser.cjs']){
 const result=spawnSync(process.execPath,[script],{stdio:'inherit',timeout:100000})
 if(result.error)throw result.error
 if(result.status!==0)process.exit(result.status||1)
}
