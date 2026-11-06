import re
import subprocess

from deploy.cloud.frontend_wiring import cloud_audio_node_type


def test_resident_motion_survives_external_pose_hook_replacement_and_failure():
    source = '''import { VRMUtils } from '@pixiv/three-vrm'
currentAudioSource?: AudioBufferSourceNode
function runVrmFrameRuntimeHook(vrm: VRM, delta: number) {
  try {
    vrmFrameRuntimeHook.value?.(vrm, delta)
  }
  catch (error) {
    console.error(error)
    emit('error', error)
  }
}
onUnmounted(() => {
  componentCleanUp('component-unmount')
})
'''
    result = cloud_audio_node_type(source)
    function = re.search(r'function runVrmFrameRuntimeHook\([\s\S]*?\n\}', result)[0]
    function = function.replace('vrm: VRM, delta: number', 'vrm, delta')
    script = '''const assert=require('node:assert/strict'),events=[];
const vrm={},residentMotion={update:(v,dt)=>{assert.equal(v,vrm);assert.equal(dt,.016);events.push('resident')}},
vrmFrameRuntimeHook={value:()=>events.push('external')},emit=()=>events.push('error');
console.error=()=>{};
''' + function + '''
runVrmFrameRuntimeHook(vrm,.016);
vrmFrameRuntimeHook.value=undefined;runVrmFrameRuntimeHook(vrm,.016);
vrmFrameRuntimeHook.value=()=>{throw Error('synthetic pose failure')};runVrmFrameRuntimeHook(vrm,.016);
assert.deepEqual(events,['external','resident','resident','error','resident']);
'''
    run = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert 'residentMotion.restore()' in result
    assert 'watch(() => props.paused' in result
    assert 'residentMotion' not in source
