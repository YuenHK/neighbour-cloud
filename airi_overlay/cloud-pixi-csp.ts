// Built only inside stage-ui-live2d, so this resolves the renderer's own
// installed Pixi 6.5.10 instance. The official interpreter replaces generated
// uniform-sync functions and works while the CSP still forbids JS eval.
import { ShaderSystem } from '@pixi/core'

import { install } from '../../../apps/stage-web/src/modules/pixi-csp.js'

install({ ShaderSystem })
