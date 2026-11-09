import{i as e}from"./chunk-DseTPa7n.js";import{$ as t,C as n,Dt as r,J as i,K as a,Nt as o,S as s,T as c,X as l,at as u,ct as d,ft as f,h as p,j as m,jt as h,k as g,kt as _,w as v,wt as y,x as b,z as x}from"./vue.runtime.esm-bundler-BpXz90Lz.js";import{it as S}from"./three.module-D0PqIStG.js";import{a as C,n as w}from"./pinia-bjccLMo5.js";import{p as T}from"./src-C73DsfM0.js";import{t as E,u as ee}from"./src-CzV4x3li.js";import{C as D,N as O,Z as te,i as k,l as A,n as ne,q as re,u as ie}from"./dist-CFS4UE1-.js";import{mt as ae}from"./use-analytics-CWU622Cn.js";import{n as j}from"./artistry-DvKiCSZz.js";import{m as oe,o as se}from"./settings-Bntd0ZHq.js";import{C as M,D as ce,O as N,T as P,c as le,g as ue,l as F,m as de,o as I,p as fe,r as L,t as R,v as z,w as B,x as V}from"./core-CpE-9IdY.js";import{n as pe}from"./animation-BG8ys2ud.js";import{t as me}from"./jszip.min-D06KXQAj.js";import{a as he,i as ge,r as _e}from"./cubism4.es-4uVBzaqy.js";import{n as ve}from"./live2d-preview-CGkxzkqB.js";import{t as ye}from"./eye-motions-DrjUJP7a.js";import"./live2d-opfs-registration-D2wBsJ3Y.js";import"./live2d-zip-loader-B34iwORn.js";function be(e,t,n){let r=n?.defaultVersion||`1.0.0`,i=y(h(t)),a=O(e,{version:r,data:h(t)},n?.storage??k?.localStorage,n),o=d(i,e=>{a.value={version:r,data:e}},{deep:!0});return d(a,s=>{try{if(`version`in a.value&&a.value.version!=null){n?.satisfiesVersionBy!=null&&!n.satisfiesVersionBy(a.value.version,r)&&(n.onVersionMismatch==null?(console.warn(`version ${a.value.version} doesn't satisfy the version ${r} for key ${e}, will reset the value to default value ${h(t)}`),a.value={version:r,data:h(t)},o.pause(),i.value=h(t),o.resume()):n.onVersionMismatch(a.value).action===`reset`&&(a.value={version:r,data:h(t)},o.pause(),i.value=h(t),o.resume())),o.pause(),i.value=a.value.data,o.resume();return}console.warn(`property key 'version' wasn't found in the value of key ${e} as ${s}, will keep the current ${h(t)}`),a.value={version:r,data:h(t)},o.pause(),i.value=h(t),o.resume()}catch(n){console.warn(`failed to un-marshal Local Storage value, possibly due to incompatible or corrupted for key ${e} value ${s}, falling back to default value ${h(t)}`,n),a.value={version:r,data:h(t)},o.pause(),i.value=h(t),o.resume()}},{immediate:!0,deep:!0}),i}function H(e,t,n){let r=be(e,o(t),n),i=re(r),{resume:a,pause:s}=d(i,e=>r.value=e,n);return d(r,e=>{s(),i.value=e,a()},n),i}var U=m({__name:`Canvas`,props:x({width:{},height:{},resolution:{default:2},maxFps:{default:0}},{state:{default:`pending`},stateModifiers:{}}),emits:[`update:state`],setup(e,{expose:n}){let r=e,o=u(e,`state`),s=y(),f=y(!1),p=y(),m=y();function h(e){return!e||e<=0?0:Math.max(1,Math.round(e))}function g(e){e.ticker.remove(e.render,e),e.ticker.add(()=>{try{e.render()}catch(t){console.error(`[Live2D] Pixi render error.`,t),e.ticker.stop()}}),e.ticker.maxFPS=h(r.maxFps)}async function _(e){o.value=`loading`,f.value=!1,ge.registerTicker(fe),ue.add(de),p.value=new ve({width:r.width*r.resolution,height:r.height*r.resolution,backgroundAlpha:0,preserveDrawingBuffer:!0,autoDensity:!1,resolution:1}),g(p.value),p.value.stage.scale.set(r.resolution),m.value=p.value.view,m.value.style.width=`100%`,m.value.style.height=`100%`,m.value.style.objectFit=`cover`,m.value.style.display=`block`,e.appendChild(p.value.view),f.value=!0,o.value=`mounted`}function b(){p.value&&(p.value.renderer.resize(r.width*r.resolution,r.height*r.resolution),p.value.stage.scale.set(r.resolution))}d([()=>r.width,()=>r.height,()=>r.resolution],b),d(()=>r.maxFps,e=>{p.value&&(p.value.ticker.maxFPS=h(e))}),a(async()=>s.value&&await _(s.value)),i(()=>p.value?.destroy());async function x(){return new Promise(e=>{if(!m.value||!p.value)return e(null);try{p.value.render()}catch(t){return console.error(`[Live2D] Pixi render error during capture.`,t),e(null)}m.value.toBlob(e)})}function S(){return m.value}return n({captureFrame:x,canvasElement:S}),(void 0)?.dispose(()=>{console.warn(`[Dev] Reload on HMR dispose is active for this component. Performing a full reload.`),window.location.reload()}),(e,n)=>(l(),c(`div`,{ref_key:`containerRef`,ref:s,"h-full":``,"w-full":``},[f.value?t(e.$slots,`default`,{key:0,app:p.value}):v(``,!0)],512))}}),W=function(e,t){return W=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},W(e,t)};function G(e,t){W(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var xe=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Se=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform float gamma;
uniform float contrast;
uniform float saturation;
uniform float brightness;
uniform float red;
uniform float green;
uniform float blue;
uniform float alpha;

void main(void)
{
    vec4 c = texture2D(uSampler, vTextureCoord);

    if (c.a > 0.0) {
        c.rgb /= c.a;

        vec3 rgb = pow(c.rgb, vec3(1. / gamma));
        rgb = mix(vec3(.5), mix(vec3(dot(vec3(.2125, .7154, .0721), rgb)), rgb, saturation), contrast);
        rgb.r *= red;
        rgb.g *= green;
        rgb.b *= blue;
        c.rgb = rgb * brightness;

        c.rgb *= c.a;
    }

    gl_FragColor = c * alpha;
}
`;(function(e){G(t,e);function t(t){var n=e.call(this,xe,Se)||this;return n.gamma=1,n.saturation=1,n.contrast=1,n.brightness=1,n.red=1,n.green=1,n.blue=1,n.alpha=1,Object.assign(n,t),n}return t.prototype.apply=function(e,t,n,r){this.uniforms.gamma=Math.max(this.gamma,1e-4),this.uniforms.saturation=this.saturation,this.uniforms.contrast=this.contrast,this.uniforms.brightness=this.brightness,this.uniforms.red=this.red,this.uniforms.green=this.green,this.uniforms.blue=this.blue,this.uniforms.alpha=this.alpha,e.applyFilter(this,t,n,r)},t})(R);var Ce=function(e,t){return Ce=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Ce(e,t)};function we(e,t){Ce(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Te=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Ee=`
varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform vec2 uOffset;

void main(void)
{
    vec4 color = vec4(0.0);

    // Sample top left pixel
    color += texture2D(uSampler, vec2(vTextureCoord.x - uOffset.x, vTextureCoord.y + uOffset.y));

    // Sample top right pixel
    color += texture2D(uSampler, vec2(vTextureCoord.x + uOffset.x, vTextureCoord.y + uOffset.y));

    // Sample bottom right pixel
    color += texture2D(uSampler, vec2(vTextureCoord.x + uOffset.x, vTextureCoord.y - uOffset.y));

    // Sample bottom left pixel
    color += texture2D(uSampler, vec2(vTextureCoord.x - uOffset.x, vTextureCoord.y - uOffset.y));

    // Average
    color *= 0.25;

    gl_FragColor = color;
}`,De=`
varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform vec2 uOffset;
uniform vec4 filterClamp;

void main(void)
{
    vec4 color = vec4(0.0);

    // Sample top left pixel
    color += texture2D(uSampler, clamp(vec2(vTextureCoord.x - uOffset.x, vTextureCoord.y + uOffset.y), filterClamp.xy, filterClamp.zw));

    // Sample top right pixel
    color += texture2D(uSampler, clamp(vec2(vTextureCoord.x + uOffset.x, vTextureCoord.y + uOffset.y), filterClamp.xy, filterClamp.zw));

    // Sample bottom right pixel
    color += texture2D(uSampler, clamp(vec2(vTextureCoord.x + uOffset.x, vTextureCoord.y - uOffset.y), filterClamp.xy, filterClamp.zw));

    // Sample bottom left pixel
    color += texture2D(uSampler, clamp(vec2(vTextureCoord.x - uOffset.x, vTextureCoord.y - uOffset.y), filterClamp.xy, filterClamp.zw));

    // Average
    color *= 0.25;

    gl_FragColor = color;
}
`,K=function(e){we(t,e);function t(t,n,r){t===void 0&&(t=4),n===void 0&&(n=3),r===void 0&&(r=!1);var i=e.call(this,Te,r?De:Ee)||this;return i._kernels=[],i._blur=4,i._quality=3,i.uniforms.uOffset=new Float32Array(2),i._pixelSize=new F,i.pixelSize=1,i._clamp=r,Array.isArray(t)?i.kernels=t:(i._blur=t,i.quality=n),i}return t.prototype.apply=function(e,t,n,r){var i=this._pixelSize.x/t._frame.width,a=this._pixelSize.y/t._frame.height,o;if(this._quality===1||this._blur===0)o=this._kernels[0]+.5,this.uniforms.uOffset[0]=o*i,this.uniforms.uOffset[1]=o*a,e.applyFilter(this,t,n,r);else{for(var s=e.getFilterTexture(),c=t,l=s,u=void 0,d=this._quality-1,f=0;f<d;f++)o=this._kernels[f]+.5,this.uniforms.uOffset[0]=o*i,this.uniforms.uOffset[1]=o*a,e.applyFilter(this,c,l,1),u=c,c=l,l=u;o=this._kernels[d]+.5,this.uniforms.uOffset[0]=o*i,this.uniforms.uOffset[1]=o*a,e.applyFilter(this,c,n,r),e.returnFilterTexture(s)}},t.prototype._updatePadding=function(){this.padding=Math.ceil(this._kernels.reduce(function(e,t){return e+t+.5},0))},t.prototype._generateKernels=function(){var e=this._blur,t=this._quality,n=[e];if(e>0)for(var r=e,i=e/t,a=1;a<t;a++)r-=i,n.push(r);this._kernels=n,this._updatePadding()},Object.defineProperty(t.prototype,`kernels`,{get:function(){return this._kernels},set:function(e){Array.isArray(e)&&e.length>0?(this._kernels=e,this._quality=e.length,this._blur=Math.max.apply(Math,e)):(this._kernels=[0],this._quality=1)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`clamp`,{get:function(){return this._clamp},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`pixelSize`,{get:function(){return this._pixelSize},set:function(e){typeof e==`number`?(this._pixelSize.x=e,this._pixelSize.y=e):Array.isArray(e)?(this._pixelSize.x=e[0],this._pixelSize.y=e[1]):e instanceof F?(this._pixelSize.x=e.x,this._pixelSize.y=e.y):(this._pixelSize.x=1,this._pixelSize.y=1)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`quality`,{get:function(){return this._quality},set:function(e){this._quality=Math.max(1,Math.round(e)),this._generateKernels()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blur`,{get:function(){return this._blur},set:function(e){this._blur=e,this._generateKernels()},enumerable:!1,configurable:!0}),t}(R),q=function(e,t){return q=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},q(e,t)};function J(e,t){q(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Y=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Oe=`
uniform sampler2D uSampler;
varying vec2 vTextureCoord;

uniform float threshold;

void main() {
    vec4 color = texture2D(uSampler, vTextureCoord);

    // A simple & fast algorithm for getting brightness.
    // It's inaccuracy , but good enought for this feature.
    float _max = max(max(color.r, color.g), color.b);
    float _min = min(min(color.r, color.g), color.b);
    float brightness = (_max + _min) * 0.5;

    if(brightness > threshold) {
        gl_FragColor = color;
    } else {
        gl_FragColor = vec4(0.0, 0.0, 0.0, 0.0);
    }
}
`,ke=function(e){J(t,e);function t(t){t===void 0&&(t=.5);var n=e.call(this,Y,Oe)||this;return n.threshold=t,n}return Object.defineProperty(t.prototype,`threshold`,{get:function(){return this.uniforms.threshold},set:function(e){this.uniforms.threshold=e},enumerable:!1,configurable:!0}),t}(R),Ae=`uniform sampler2D uSampler;
varying vec2 vTextureCoord;

uniform sampler2D bloomTexture;
uniform float bloomScale;
uniform float brightness;

void main() {
    vec4 color = texture2D(uSampler, vTextureCoord);
    color.rgb *= brightness;
    vec4 bloomColor = vec4(texture2D(bloomTexture, vTextureCoord).rgb, 0.0);
    bloomColor.rgb *= bloomScale;
    gl_FragColor = color + bloomColor;
}
`;(function(e){J(t,e);function t(n){var r=e.call(this,Y,Ae)||this;r.bloomScale=1,r.brightness=1,r._resolution=M.FILTER_RESOLUTION,typeof n==`number`&&(n={threshold:n});var i=Object.assign(t.defaults,n);r.bloomScale=i.bloomScale,r.brightness=i.brightness;var a=i.kernels,o=i.blur,s=i.quality,c=i.pixelSize,l=i.resolution;return r._extractFilter=new ke(i.threshold),r._extractFilter.resolution=l,r._blurFilter=a?new K(a):new K(o,s),r.pixelSize=c,r.resolution=l,r}return t.prototype.apply=function(e,t,n,r,i){var a=e.getFilterTexture();this._extractFilter.apply(e,t,a,1,i);var o=e.getFilterTexture();this._blurFilter.apply(e,a,o,1),this.uniforms.bloomScale=this.bloomScale,this.uniforms.brightness=this.brightness,this.uniforms.bloomTexture=o,e.applyFilter(this,t,n,r),e.returnFilterTexture(o),e.returnFilterTexture(a)},Object.defineProperty(t.prototype,`resolution`,{get:function(){return this._resolution},set:function(e){this._resolution=e,this._extractFilter&&(this._extractFilter.resolution=e),this._blurFilter&&(this._blurFilter.resolution=e)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`threshold`,{get:function(){return this._extractFilter.threshold},set:function(e){this._extractFilter.threshold=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`kernels`,{get:function(){return this._blurFilter.kernels},set:function(e){this._blurFilter.kernels=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blur`,{get:function(){return this._blurFilter.blur},set:function(e){this._blurFilter.blur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`quality`,{get:function(){return this._blurFilter.quality},set:function(e){this._blurFilter.quality=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`pixelSize`,{get:function(){return this._blurFilter.pixelSize},set:function(e){this._blurFilter.pixelSize=e},enumerable:!1,configurable:!0}),t.defaults={threshold:.5,bloomScale:1,brightness:1,kernels:null,blur:8,quality:4,pixelSize:1,resolution:M.FILTER_RESOLUTION},t})(R);var je=function(e,t){return je=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},je(e,t)};function Me(e,t){je(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Ne=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Pe=`varying vec2 vTextureCoord;

uniform vec4 filterArea;
uniform float pixelSize;
uniform sampler2D uSampler;

vec2 mapCoord( vec2 coord )
{
    coord *= filterArea.xy;
    coord += filterArea.zw;

    return coord;
}

vec2 unmapCoord( vec2 coord )
{
    coord -= filterArea.zw;
    coord /= filterArea.xy;

    return coord;
}

vec2 pixelate(vec2 coord, vec2 size)
{
    return floor( coord / size ) * size;
}

vec2 getMod(vec2 coord, vec2 size)
{
    return mod( coord , size) / size;
}

float character(float n, vec2 p)
{
    p = floor(p*vec2(4.0, -4.0) + 2.5);

    if (clamp(p.x, 0.0, 4.0) == p.x)
    {
        if (clamp(p.y, 0.0, 4.0) == p.y)
        {
            if (int(mod(n/exp2(p.x + 5.0*p.y), 2.0)) == 1) return 1.0;
        }
    }
    return 0.0;
}

void main()
{
    vec2 coord = mapCoord(vTextureCoord);

    // get the rounded color..
    vec2 pixCoord = pixelate(coord, vec2(pixelSize));
    pixCoord = unmapCoord(pixCoord);

    vec4 color = texture2D(uSampler, pixCoord);

    // determine the character to use
    float gray = (color.r + color.g + color.b) / 3.0;

    float n =  65536.0;             // .
    if (gray > 0.2) n = 65600.0;    // :
    if (gray > 0.3) n = 332772.0;   // *
    if (gray > 0.4) n = 15255086.0; // o
    if (gray > 0.5) n = 23385164.0; // &
    if (gray > 0.6) n = 15252014.0; // 8
    if (gray > 0.7) n = 13199452.0; // @
    if (gray > 0.8) n = 11512810.0; // #

    // get the mod..
    vec2 modd = getMod(coord, vec2(pixelSize));

    gl_FragColor = color * character( n, vec2(-1.0) + modd * 2.0);

}
`;(function(e){Me(t,e);function t(t){t===void 0&&(t=8);var n=e.call(this,Ne,Pe)||this;return n.size=t,n}return Object.defineProperty(t.prototype,`size`,{get:function(){return this.uniforms.pixelSize},set:function(e){this.uniforms.pixelSize=e},enumerable:!1,configurable:!0}),t})(R);var Fe=function(e,t){return Fe=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Fe(e,t)};function Ie(e,t){Fe(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Le=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Re=`precision mediump float;

varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;

uniform float transformX;
uniform float transformY;
uniform vec3 lightColor;
uniform float lightAlpha;
uniform vec3 shadowColor;
uniform float shadowAlpha;

void main(void) {
    vec2 transform = vec2(1.0 / filterArea) * vec2(transformX, transformY);
    vec4 color = texture2D(uSampler, vTextureCoord);
    float light = texture2D(uSampler, vTextureCoord - transform).a;
    float shadow = texture2D(uSampler, vTextureCoord + transform).a;

    color.rgb = mix(color.rgb, lightColor, clamp((color.a - light) * lightAlpha, 0.0, 1.0));
    color.rgb = mix(color.rgb, shadowColor, clamp((color.a - shadow) * shadowAlpha, 0.0, 1.0));
    gl_FragColor = vec4(color.rgb * color.a, color.a);
}
`;(function(e){Ie(t,e);function t(t){var n=e.call(this,Le,Re)||this;return n._thickness=2,n._angle=0,n.uniforms.lightColor=new Float32Array(3),n.uniforms.shadowColor=new Float32Array(3),Object.assign(n,{rotation:45,thickness:2,lightColor:16777215,lightAlpha:.7,shadowColor:0,shadowAlpha:.7},t),n.padding=1,n}return t.prototype._updateTransform=function(){this.uniforms.transformX=this._thickness*Math.cos(this._angle),this.uniforms.transformY=this._thickness*Math.sin(this._angle)},Object.defineProperty(t.prototype,`rotation`,{get:function(){return this._angle/I},set:function(e){this._angle=e*I,this._updateTransform()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`thickness`,{get:function(){return this._thickness},set:function(e){this._thickness=e,this._updateTransform()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`lightColor`,{get:function(){return V(this.uniforms.lightColor)},set:function(e){z(e,this.uniforms.lightColor)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`lightAlpha`,{get:function(){return this.uniforms.lightAlpha},set:function(e){this.uniforms.lightAlpha=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`shadowColor`,{get:function(){return V(this.uniforms.shadowColor)},set:function(e){z(e,this.uniforms.shadowColor)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`shadowAlpha`,{get:function(){return this.uniforms.shadowAlpha},set:function(e){this.uniforms.shadowAlpha=e},enumerable:!1,configurable:!0}),t})(R);var ze=function(e,t){return ze=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)t.hasOwnProperty(n)&&(e[n]=t[n])},ze(e,t)};function Be(e,t){ze(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Ve=`varying vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform float uAlpha;

void main(void)
{
   gl_FragColor = texture2D(uSampler, vTextureCoord) * uAlpha;
}
`,He=function(e){Be(t,e);function t(t){t===void 0&&(t=1);var n=e.call(this,`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Ve,{uAlpha:1})||this;return n.alpha=t,n}return Object.defineProperty(t.prototype,`alpha`,{get:function(){return this.uniforms.uAlpha},set:function(e){this.uniforms.uAlpha=e},enumerable:!1,configurable:!0}),t}(R),Ue=function(e,t){return Ue=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)t.hasOwnProperty(n)&&(e[n]=t[n])},Ue(e,t)};function We(e,t){Ue(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Ge=`
    attribute vec2 aVertexPosition;

    uniform mat3 projectionMatrix;

    uniform float strength;

    varying vec2 vBlurTexCoords[%size%];

    uniform vec4 inputSize;
    uniform vec4 outputFrame;

    vec4 filterVertexPosition( void )
    {
        vec2 position = aVertexPosition * max(outputFrame.zw, vec2(0.)) + outputFrame.xy;

        return vec4((projectionMatrix * vec3(position, 1.0)).xy, 0.0, 1.0);
    }

    vec2 filterTextureCoord( void )
    {
        return aVertexPosition * (outputFrame.zw * inputSize.zw);
    }

    void main(void)
    {
        gl_Position = filterVertexPosition();

        vec2 textureCoord = filterTextureCoord();
        %blur%
    }`;function Ke(e,t){for(var n=Math.ceil(e/2),r=Ge,i=``,a=t?`vBlurTexCoords[%index%] =  textureCoord + vec2(%sampleIndex% * strength, 0.0);`:`vBlurTexCoords[%index%] =  textureCoord + vec2(0.0, %sampleIndex% * strength);`,o=0;o<e;o++){var s=a.replace(`%index%`,o.toString());s=s.replace(`%sampleIndex%`,o-(n-1)+`.0`),i+=s,i+=`
`}return r=r.replace(`%blur%`,i),r=r.replace(`%size%`,e.toString()),r}var qe={5:[.153388,.221461,.250301],7:[.071303,.131514,.189879,.214607],9:[.028532,.067234,.124009,.179044,.20236],11:[.0093,.028002,.065984,.121703,.175713,.198596],13:[.002406,.009255,.027867,.065666,.121117,.174868,.197641],15:[489e-6,.002403,.009246,.02784,.065602,.120999,.174697,.197448]},Je=[`varying vec2 vBlurTexCoords[%size%];`,`uniform sampler2D uSampler;`,`void main(void)`,`{`,`    gl_FragColor = vec4(0.0);`,`    %blur%`,`}`].join(`
`);function Ye(e){for(var t=qe[e],n=t.length,r=Je,i=``,a=`gl_FragColor += texture2D(uSampler, vBlurTexCoords[%index%]) * %value%;`,o,s=0;s<e;s++){var c=a.replace(`%index%`,s.toString());o=s,s>=n&&(o=e-s-1),c=c.replace(`%value%`,t[o].toString()),i+=c,i+=`
`}return r=r.replace(`%blur%`,i),r=r.replace(`%size%`,e.toString()),r}var Xe=function(e){We(t,e);function t(t,n,r,i,a){n===void 0&&(n=8),r===void 0&&(r=4),i===void 0&&(i=M.FILTER_RESOLUTION),a===void 0&&(a=5);var o=this,s=Ke(a,t),c=Ye(a);return o=e.call(this,s,c)||this,o.horizontal=t,o.resolution=i,o._quality=0,o.quality=r,o.blur=n,o}return t.prototype.apply=function(e,t,n,r){if(n?this.horizontal?this.uniforms.strength=1/n.width*(n.width/t.width):this.uniforms.strength=1/n.height*(n.height/t.height):this.horizontal?this.uniforms.strength=1/e.renderer.width*(e.renderer.width/t.width):this.uniforms.strength=1/e.renderer.height*(e.renderer.height/t.height),this.uniforms.strength*=this.strength,this.uniforms.strength/=this.passes,this.passes===1)e.applyFilter(this,t,n,r);else{var i=e.getFilterTexture(),a=e.renderer,o=t,s=i;this.state.blend=!1,e.applyFilter(this,o,s,P.CLEAR);for(var c=1;c<this.passes-1;c++){e.bindAndClear(o,P.BLIT),this.uniforms.uSampler=s;var l=s;s=o,o=l,a.shader.bind(this),a.geometry.draw(5)}this.state.blend=!0,e.applyFilter(this,s,n,r),e.returnFilterTexture(i)}},Object.defineProperty(t.prototype,`blur`,{get:function(){return this.strength},set:function(e){this.padding=1+Math.abs(e)*2,this.strength=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`quality`,{get:function(){return this._quality},set:function(e){this._quality=e,this.passes=e},enumerable:!1,configurable:!0}),t}(R);(function(e){We(t,e);function t(t,n,r,i){t===void 0&&(t=8),n===void 0&&(n=4),r===void 0&&(r=M.FILTER_RESOLUTION),i===void 0&&(i=5);var a=e.call(this)||this;return a.blurXFilter=new Xe(!0,t,n,r,i),a.blurYFilter=new Xe(!1,t,n,r,i),a.resolution=r,a.quality=n,a.blur=t,a.repeatEdgePixels=!1,a}return t.prototype.apply=function(e,t,n,r){var i=Math.abs(this.blurXFilter.strength),a=Math.abs(this.blurYFilter.strength);if(i&&a){var o=e.getFilterTexture();this.blurXFilter.apply(e,t,o,P.CLEAR),this.blurYFilter.apply(e,o,n,r),e.returnFilterTexture(o)}else a?this.blurYFilter.apply(e,t,n,r):this.blurXFilter.apply(e,t,n,r)},t.prototype.updatePadding=function(){this._repeatEdgePixels?this.padding=0:this.padding=Math.max(Math.abs(this.blurXFilter.strength),Math.abs(this.blurYFilter.strength))*2},Object.defineProperty(t.prototype,`blur`,{get:function(){return this.blurXFilter.blur},set:function(e){this.blurXFilter.blur=this.blurYFilter.blur=e,this.updatePadding()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`quality`,{get:function(){return this.blurXFilter.quality},set:function(e){this.blurXFilter.quality=this.blurYFilter.quality=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blurX`,{get:function(){return this.blurXFilter.blur},set:function(e){this.blurXFilter.blur=e,this.updatePadding()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blurY`,{get:function(){return this.blurYFilter.blur},set:function(e){this.blurYFilter.blur=e,this.updatePadding()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blendMode`,{get:function(){return this.blurYFilter.blendMode},set:function(e){this.blurYFilter.blendMode=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`repeatEdgePixels`,{get:function(){return this._repeatEdgePixels},set:function(e){this._repeatEdgePixels=e,this.updatePadding()},enumerable:!1,configurable:!0}),t})(R);var Ze=function(e,t){return Ze=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Ze(e,t)};function Qe(e,t){Ze(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}(function(e){Qe(t,e);function t(t,n,r,i){t===void 0&&(t=2),n===void 0&&(n=4),r===void 0&&(r=M.FILTER_RESOLUTION),i===void 0&&(i=5);var a=e.call(this)||this,o,s;return typeof t==`number`?(o=t,s=t):t instanceof F?(o=t.x,s=t.y):Array.isArray(t)&&(o=t[0],s=t[1]),a.blurXFilter=new Xe(!0,o,n,r,i),a.blurYFilter=new Xe(!1,s,n,r,i),a.blurYFilter.blendMode=B.SCREEN,a.defaultFilter=new He,a}return t.prototype.apply=function(e,t,n,r){var i=e.getFilterTexture();this.defaultFilter.apply(e,t,n,r),this.blurXFilter.apply(e,t,i,1),this.blurYFilter.apply(e,i,n,0),e.returnFilterTexture(i)},Object.defineProperty(t.prototype,`blur`,{get:function(){return this.blurXFilter.blur},set:function(e){this.blurXFilter.blur=this.blurYFilter.blur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blurX`,{get:function(){return this.blurXFilter.blur},set:function(e){this.blurXFilter.blur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blurY`,{get:function(){return this.blurYFilter.blur},set:function(e){this.blurYFilter.blur=e},enumerable:!1,configurable:!0}),t})(R);var $e=function(e,t){return $e=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},$e(e,t)};function et(e,t){$e(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var tt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,nt=`uniform float radius;
uniform float strength;
uniform vec2 center;
uniform sampler2D uSampler;
varying vec2 vTextureCoord;

uniform vec4 filterArea;
uniform vec4 filterClamp;
uniform vec2 dimensions;

void main()
{
    vec2 coord = vTextureCoord * filterArea.xy;
    coord -= center * dimensions.xy;
    float distance = length(coord);
    if (distance < radius) {
        float percent = distance / radius;
        if (strength > 0.0) {
            coord *= mix(1.0, smoothstep(0.0, radius / distance, percent), strength * 0.75);
        } else {
            coord *= mix(1.0, pow(percent, 1.0 + strength * 0.75) * radius / distance, 1.0 - percent);
        }
    }
    coord += center * dimensions.xy;
    coord /= filterArea.xy;
    vec2 clampedCoord = clamp(coord, filterClamp.xy, filterClamp.zw);
    vec4 color = texture2D(uSampler, clampedCoord);
    if (coord != clampedCoord) {
        color *= max(0.0, 1.0 - length(coord - clampedCoord));
    }

    gl_FragColor = color;
}
`;(function(e){et(t,e);function t(n){var r=e.call(this,tt,nt)||this;return r.uniforms.dimensions=new Float32Array(2),Object.assign(r,t.defaults,n),r}return t.prototype.apply=function(e,t,n,r){var i=t.filterFrame,a=i.width,o=i.height;this.uniforms.dimensions[0]=a,this.uniforms.dimensions[1]=o,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`radius`,{get:function(){return this.uniforms.radius},set:function(e){this.uniforms.radius=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`strength`,{get:function(){return this.uniforms.strength},set:function(e){this.uniforms.strength=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`center`,{get:function(){return this.uniforms.center},set:function(e){this.uniforms.center=e},enumerable:!1,configurable:!0}),t.defaults={center:[.5,.5],radius:100,strength:1},t})(R);var rt=function(e,t){return rt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},rt(e,t)};function it(e,t){rt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var at=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,ot=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform sampler2D colorMap;
uniform float _mix;
uniform float _size;
uniform float _sliceSize;
uniform float _slicePixelSize;
uniform float _sliceInnerSize;
void main() {
    vec4 color = texture2D(uSampler, vTextureCoord.xy);

    vec4 adjusted;
    if (color.a > 0.0) {
        color.rgb /= color.a;
        float innerWidth = _size - 1.0;
        float zSlice0 = min(floor(color.b * innerWidth), innerWidth);
        float zSlice1 = min(zSlice0 + 1.0, innerWidth);
        float xOffset = _slicePixelSize * 0.5 + color.r * _sliceInnerSize;
        float s0 = xOffset + (zSlice0 * _sliceSize);
        float s1 = xOffset + (zSlice1 * _sliceSize);
        float yOffset = _sliceSize * 0.5 + color.g * (1.0 - _sliceSize);
        vec4 slice0Color = texture2D(colorMap, vec2(s0,yOffset));
        vec4 slice1Color = texture2D(colorMap, vec2(s1,yOffset));
        float zOffset = fract(color.b * innerWidth);
        adjusted = mix(slice0Color, slice1Color, zOffset);

        color.rgb *= color.a;
    }
    gl_FragColor = vec4(mix(color, adjusted, _mix).rgb, color.a);

}`;(function(e){it(t,e);function t(t,n,r){n===void 0&&(n=!1),r===void 0&&(r=1);var i=e.call(this,at,ot)||this;return i.mix=1,i._size=0,i._sliceSize=0,i._slicePixelSize=0,i._sliceInnerSize=0,i._nearest=!1,i._scaleMode=null,i._colorMap=null,i._scaleMode=null,i.nearest=n,i.mix=r,i.colorMap=t,i}return t.prototype.apply=function(e,t,n,r){this.uniforms._mix=this.mix,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`colorSize`,{get:function(){return this._size},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`colorMap`,{get:function(){return this._colorMap},set:function(e){e&&(e instanceof L||(e=L.from(e)),e?.baseTexture&&(e.baseTexture.scaleMode=this._scaleMode,e.baseTexture.mipmap=ce.OFF,this._size=e.height,this._sliceSize=1/this._size,this._slicePixelSize=this._sliceSize/this._size,this._sliceInnerSize=this._slicePixelSize*(this._size-1),this.uniforms._size=this._size,this.uniforms._sliceSize=this._sliceSize,this.uniforms._slicePixelSize=this._slicePixelSize,this.uniforms._sliceInnerSize=this._sliceInnerSize,this.uniforms.colorMap=e),this._colorMap=e)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`nearest`,{get:function(){return this._nearest},set:function(e){this._nearest=e,this._scaleMode=e?N.NEAREST:N.LINEAR;var t=this._colorMap;t&&t.baseTexture&&(t.baseTexture._glTextures={},t.baseTexture.scaleMode=this._scaleMode,t.baseTexture.mipmap=ce.OFF,t._updateID++,t.baseTexture.emit(`update`,t.baseTexture))},enumerable:!1,configurable:!0}),t.prototype.updateColorMap=function(){var e=this._colorMap;e&&e.baseTexture&&(e._updateID++,e.baseTexture.emit(`update`,e.baseTexture),this.colorMap=e)},t.prototype.destroy=function(t){t===void 0&&(t=!1),this._colorMap&&this._colorMap.destroy(t),e.prototype.destroy.call(this)},t})(R);var st=function(e,t){return st=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},st(e,t)};function ct(e,t){st(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var lt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,ut=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec3 color;
uniform float alpha;

void main(void) {
    vec4 currentColor = texture2D(uSampler, vTextureCoord);
    gl_FragColor = vec4(mix(currentColor.rgb, color.rgb, currentColor.a * alpha), currentColor.a);
}
`;(function(e){ct(t,e);function t(t,n){t===void 0&&(t=0),n===void 0&&(n=1);var r=e.call(this,lt,ut)||this;return r._color=0,r._alpha=1,r.uniforms.color=new Float32Array(3),r.color=t,r.alpha=n,r}return Object.defineProperty(t.prototype,`color`,{get:function(){return this._color},set:function(e){var t=this.uniforms.color;typeof e==`number`?(z(e,t),this._color=e):(t[0]=e[0],t[1]=e[1],t[2]=e[2],this._color=V(t))},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`alpha`,{get:function(){return this._alpha},set:function(e){this.uniforms.alpha=e,this._alpha=e},enumerable:!1,configurable:!0}),t})(R);var dt=function(e,t){return dt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},dt(e,t)};function ft(e,t){dt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var pt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,mt=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec3 originalColor;
uniform vec3 newColor;
uniform float epsilon;
void main(void) {
    vec4 currentColor = texture2D(uSampler, vTextureCoord);
    vec3 colorDiff = originalColor - (currentColor.rgb / max(currentColor.a, 0.0000000001));
    float colorDistance = length(colorDiff);
    float doReplace = step(colorDistance, epsilon);
    gl_FragColor = vec4(mix(currentColor.rgb, (newColor + colorDiff) * currentColor.a, doReplace), currentColor.a);
}
`;(function(e){ft(t,e);function t(t,n,r){t===void 0&&(t=16711680),n===void 0&&(n=0),r===void 0&&(r=.4);var i=e.call(this,pt,mt)||this;return i._originalColor=16711680,i._newColor=0,i.uniforms.originalColor=new Float32Array(3),i.uniforms.newColor=new Float32Array(3),i.originalColor=t,i.newColor=n,i.epsilon=r,i}return Object.defineProperty(t.prototype,`originalColor`,{get:function(){return this._originalColor},set:function(e){var t=this.uniforms.originalColor;typeof e==`number`?(z(e,t),this._originalColor=e):(t[0]=e[0],t[1]=e[1],t[2]=e[2],this._originalColor=V(t))},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`newColor`,{get:function(){return this._newColor},set:function(e){var t=this.uniforms.newColor;typeof e==`number`?(z(e,t),this._newColor=e):(t[0]=e[0],t[1]=e[1],t[2]=e[2],this._newColor=V(t))},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`epsilon`,{get:function(){return this.uniforms.epsilon},set:function(e){this.uniforms.epsilon=e},enumerable:!1,configurable:!0}),t})(R);var ht=function(e,t){return ht=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},ht(e,t)};function gt(e,t){ht(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var _t=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,vt=`precision mediump float;

varying mediump vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform vec2 texelSize;
uniform float matrix[9];

void main(void)
{
   vec4 c11 = texture2D(uSampler, vTextureCoord - texelSize); // top left
   vec4 c12 = texture2D(uSampler, vec2(vTextureCoord.x, vTextureCoord.y - texelSize.y)); // top center
   vec4 c13 = texture2D(uSampler, vec2(vTextureCoord.x + texelSize.x, vTextureCoord.y - texelSize.y)); // top right

   vec4 c21 = texture2D(uSampler, vec2(vTextureCoord.x - texelSize.x, vTextureCoord.y)); // mid left
   vec4 c22 = texture2D(uSampler, vTextureCoord); // mid center
   vec4 c23 = texture2D(uSampler, vec2(vTextureCoord.x + texelSize.x, vTextureCoord.y)); // mid right

   vec4 c31 = texture2D(uSampler, vec2(vTextureCoord.x - texelSize.x, vTextureCoord.y + texelSize.y)); // bottom left
   vec4 c32 = texture2D(uSampler, vec2(vTextureCoord.x, vTextureCoord.y + texelSize.y)); // bottom center
   vec4 c33 = texture2D(uSampler, vTextureCoord + texelSize); // bottom right

   gl_FragColor =
       c11 * matrix[0] + c12 * matrix[1] + c13 * matrix[2] +
       c21 * matrix[3] + c22 * matrix[4] + c23 * matrix[5] +
       c31 * matrix[6] + c32 * matrix[7] + c33 * matrix[8];

   gl_FragColor.a = c22.a;
}
`;(function(e){gt(t,e);function t(t,n,r){n===void 0&&(n=200),r===void 0&&(r=200);var i=e.call(this,_t,vt)||this;return i.uniforms.texelSize=new Float32Array(2),i.uniforms.matrix=new Float32Array(9),t!==void 0&&(i.matrix=t),i.width=n,i.height=r,i}return Object.defineProperty(t.prototype,`matrix`,{get:function(){return this.uniforms.matrix},set:function(e){var t=this;e.forEach(function(e,n){t.uniforms.matrix[n]=e})},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`width`,{get:function(){return 1/this.uniforms.texelSize[0]},set:function(e){this.uniforms.texelSize[0]=1/e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`height`,{get:function(){return 1/this.uniforms.texelSize[1]},set:function(e){this.uniforms.texelSize[1]=1/e},enumerable:!1,configurable:!0}),t})(R);var yt=function(e,t){return yt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},yt(e,t)};function bt(e,t){yt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var xt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,St=`precision mediump float;

varying vec2 vTextureCoord;

uniform sampler2D uSampler;

void main(void)
{
    float lum = length(texture2D(uSampler, vTextureCoord.xy).rgb);

    gl_FragColor = vec4(1.0, 1.0, 1.0, 1.0);

    if (lum < 1.00)
    {
        if (mod(gl_FragCoord.x + gl_FragCoord.y, 10.0) == 0.0)
        {
            gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        }
    }

    if (lum < 0.75)
    {
        if (mod(gl_FragCoord.x - gl_FragCoord.y, 10.0) == 0.0)
        {
            gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        }
    }

    if (lum < 0.50)
    {
        if (mod(gl_FragCoord.x + gl_FragCoord.y - 5.0, 10.0) == 0.0)
        {
            gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        }
    }

    if (lum < 0.3)
    {
        if (mod(gl_FragCoord.x - gl_FragCoord.y - 5.0, 10.0) == 0.0)
        {
            gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        }
    }
}
`;(function(e){bt(t,e);function t(){return e.call(this,xt,St)||this}return t})(R);var Ct=function(e,t){return Ct=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Ct(e,t)};function wt(e,t){Ct(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Tt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Et=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform vec4 filterArea;
uniform vec2 dimensions;

const float SQRT_2 = 1.414213;

const float light = 1.0;

uniform float curvature;
uniform float lineWidth;
uniform float lineContrast;
uniform bool verticalLine;
uniform float noise;
uniform float noiseSize;

uniform float vignetting;
uniform float vignettingAlpha;
uniform float vignettingBlur;

uniform float seed;
uniform float time;

float rand(vec2 co) {
    return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
}

void main(void)
{
    vec2 pixelCoord = vTextureCoord.xy * filterArea.xy;
    vec2 dir = vec2(vTextureCoord.xy * filterArea.xy / dimensions - vec2(0.5, 0.5));
    
    gl_FragColor = texture2D(uSampler, vTextureCoord);
    vec3 rgb = gl_FragColor.rgb;

    if (noise > 0.0 && noiseSize > 0.0)
    {
        pixelCoord.x = floor(pixelCoord.x / noiseSize);
        pixelCoord.y = floor(pixelCoord.y / noiseSize);
        float _noise = rand(pixelCoord * noiseSize * seed) - 0.5;
        rgb += _noise * noise;
    }

    if (lineWidth > 0.0)
    {
        float _c = curvature > 0. ? curvature : 1.;
        float k = curvature > 0. ?(length(dir * dir) * 0.25 * _c * _c + 0.935 * _c) : 1.;
        vec2 uv = dir * k;

        float v = (verticalLine ? uv.x * dimensions.x : uv.y * dimensions.y) * min(1.0, 2.0 / lineWidth ) / _c;
        float j = 1. + cos(v * 1.2 - time) * 0.5 * lineContrast;
        rgb *= j;
        float segment = verticalLine ? mod((dir.x + .5) * dimensions.x, 4.) : mod((dir.y + .5) * dimensions.y, 4.);
        rgb *= 0.99 + ceil(segment) * 0.015;
    }

    if (vignetting > 0.0)
    {
        float outter = SQRT_2 - vignetting * SQRT_2;
        float darker = clamp((outter - length(dir) * SQRT_2) / ( 0.00001 + vignettingBlur * SQRT_2), 0.0, 1.0);
        rgb *= darker + (1.0 - darker) * (1.0 - vignettingAlpha);
    }

    gl_FragColor.rgb = rgb;
}
`;(function(e){wt(t,e);function t(n){var r=e.call(this,Tt,Et)||this;return r.time=0,r.seed=0,r.uniforms.dimensions=new Float32Array(2),Object.assign(r,t.defaults,n),r}return t.prototype.apply=function(e,t,n,r){var i=t.filterFrame,a=i.width,o=i.height;this.uniforms.dimensions[0]=a,this.uniforms.dimensions[1]=o,this.uniforms.seed=this.seed,this.uniforms.time=this.time,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`curvature`,{get:function(){return this.uniforms.curvature},set:function(e){this.uniforms.curvature=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`lineWidth`,{get:function(){return this.uniforms.lineWidth},set:function(e){this.uniforms.lineWidth=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`lineContrast`,{get:function(){return this.uniforms.lineContrast},set:function(e){this.uniforms.lineContrast=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`verticalLine`,{get:function(){return this.uniforms.verticalLine},set:function(e){this.uniforms.verticalLine=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`noise`,{get:function(){return this.uniforms.noise},set:function(e){this.uniforms.noise=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`noiseSize`,{get:function(){return this.uniforms.noiseSize},set:function(e){this.uniforms.noiseSize=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`vignetting`,{get:function(){return this.uniforms.vignetting},set:function(e){this.uniforms.vignetting=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`vignettingAlpha`,{get:function(){return this.uniforms.vignettingAlpha},set:function(e){this.uniforms.vignettingAlpha=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`vignettingBlur`,{get:function(){return this.uniforms.vignettingBlur},set:function(e){this.uniforms.vignettingBlur=e},enumerable:!1,configurable:!0}),t.defaults={curvature:1,lineWidth:1,lineContrast:.25,verticalLine:!1,noise:0,noiseSize:1,seed:0,vignetting:.3,vignettingAlpha:1,vignettingBlur:.3,time:0},t})(R);var Dt=function(e,t){return Dt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Dt(e,t)};function Ot(e,t){Dt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var kt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,At=`precision mediump float;

varying vec2 vTextureCoord;
varying vec4 vColor;

uniform vec4 filterArea;
uniform sampler2D uSampler;

uniform float angle;
uniform float scale;

float pattern()
{
   float s = sin(angle), c = cos(angle);
   vec2 tex = vTextureCoord * filterArea.xy;
   vec2 point = vec2(
       c * tex.x - s * tex.y,
       s * tex.x + c * tex.y
   ) * scale;
   return (sin(point.x) * sin(point.y)) * 4.0;
}

void main()
{
   vec4 color = texture2D(uSampler, vTextureCoord);
   float average = (color.r + color.g + color.b) / 3.0;
   gl_FragColor = vec4(vec3(average * 10.0 - 5.0 + pattern()), color.a);
}
`;(function(e){Ot(t,e);function t(t,n){t===void 0&&(t=1),n===void 0&&(n=5);var r=e.call(this,kt,At)||this;return r.scale=t,r.angle=n,r}return Object.defineProperty(t.prototype,`scale`,{get:function(){return this.uniforms.scale},set:function(e){this.uniforms.scale=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`angle`,{get:function(){return this.uniforms.angle},set:function(e){this.uniforms.angle=e},enumerable:!1,configurable:!0}),t})(R);var jt=function(e,t){return jt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},jt(e,t)};function Mt(e,t){jt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var X=function(){return X=Object.assign||function(e){for(var t=arguments,n,r=1,i=arguments.length;r<i;r++)for(var a in n=t[r],n)Object.prototype.hasOwnProperty.call(n,a)&&(e[a]=n[a]);return e},X.apply(this,arguments)},Nt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Pt=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform float alpha;
uniform vec3 color;

uniform vec2 shift;
uniform vec4 inputSize;

void main(void){
    vec4 sample = texture2D(uSampler, vTextureCoord - shift * inputSize.zw);

    // Premultiply alpha
    sample.rgb = color.rgb * sample.a;

    // alpha user alpha
    sample *= alpha;

    gl_FragColor = sample;
}`,Ft=function(e){Mt(t,e);function t(n){var r=e.call(this)||this;r.angle=45,r._distance=5,r._resolution=M.FILTER_RESOLUTION;var i=n?X(X({},t.defaults),n):t.defaults,a=i.kernels,o=i.blur,s=i.quality,c=i.pixelSize,l=i.resolution;r._tintFilter=new R(Nt,Pt),r._tintFilter.uniforms.color=new Float32Array(4),r._tintFilter.uniforms.shift=new F,r._tintFilter.resolution=l,r._blurFilter=a?new K(a):new K(o,s),r.pixelSize=c,r.resolution=l;var u=i.shadowOnly,d=i.rotation,f=i.distance,p=i.alpha,m=i.color;return r.shadowOnly=u,r.rotation=d,r.distance=f,r.alpha=p,r.color=m,r._updatePadding(),r}return t.prototype.apply=function(e,t,n,r){var i=e.getFilterTexture();this._tintFilter.apply(e,t,i,1),this._blurFilter.apply(e,i,n,r),this.shadowOnly!==!0&&e.applyFilter(this,t,n,0),e.returnFilterTexture(i)},t.prototype._updatePadding=function(){this.padding=this.distance+this.blur*2},t.prototype._updateShift=function(){this._tintFilter.uniforms.shift.set(this.distance*Math.cos(this.angle),this.distance*Math.sin(this.angle))},Object.defineProperty(t.prototype,`resolution`,{get:function(){return this._resolution},set:function(e){this._resolution=e,this._tintFilter&&(this._tintFilter.resolution=e),this._blurFilter&&(this._blurFilter.resolution=e)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`distance`,{get:function(){return this._distance},set:function(e){this._distance=e,this._updatePadding(),this._updateShift()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`rotation`,{get:function(){return this.angle/I},set:function(e){this.angle=e*I,this._updateShift()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`alpha`,{get:function(){return this._tintFilter.uniforms.alpha},set:function(e){this._tintFilter.uniforms.alpha=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`color`,{get:function(){return V(this._tintFilter.uniforms.color)},set:function(e){z(e,this._tintFilter.uniforms.color)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`kernels`,{get:function(){return this._blurFilter.kernels},set:function(e){this._blurFilter.kernels=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blur`,{get:function(){return this._blurFilter.blur},set:function(e){this._blurFilter.blur=e,this._updatePadding()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`quality`,{get:function(){return this._blurFilter.quality},set:function(e){this._blurFilter.quality=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`pixelSize`,{get:function(){return this._blurFilter.pixelSize},set:function(e){this._blurFilter.pixelSize=e},enumerable:!1,configurable:!0}),t.defaults={rotation:45,distance:5,color:0,alpha:.5,shadowOnly:!1,kernels:null,blur:2,quality:3,pixelSize:1,resolution:M.FILTER_RESOLUTION},t}(R),It=function(e,t){return It=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},It(e,t)};function Lt(e,t){It(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Rt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,zt=`precision mediump float;

varying vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform float strength;
uniform vec4 filterArea;


void main(void)
{
	vec2 onePixel = vec2(1.0 / filterArea);

	vec4 color;

	color.rgb = vec3(0.5);

	color -= texture2D(uSampler, vTextureCoord - onePixel) * strength;
	color += texture2D(uSampler, vTextureCoord + onePixel) * strength;

	color.rgb = vec3((color.r + color.g + color.b) / 3.0);

	float alpha = texture2D(uSampler, vTextureCoord).a;

	gl_FragColor = vec4(color.rgb * alpha, alpha);
}
`;(function(e){Lt(t,e);function t(t){t===void 0&&(t=5);var n=e.call(this,Rt,zt)||this;return n.strength=t,n}return Object.defineProperty(t.prototype,`strength`,{get:function(){return this.uniforms.strength},set:function(e){this.uniforms.strength=e},enumerable:!1,configurable:!0}),t})(R);var Bt=function(e,t){return Bt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Bt(e,t)};function Vt(e,t){Bt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Ht=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Ut=`// precision highp float;

varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform vec4 filterArea;
uniform vec4 filterClamp;
uniform vec2 dimensions;
uniform float aspect;

uniform sampler2D displacementMap;
uniform float offset;
uniform float sinDir;
uniform float cosDir;
uniform int fillMode;

uniform float seed;
uniform vec2 red;
uniform vec2 green;
uniform vec2 blue;

const int TRANSPARENT = 0;
const int ORIGINAL = 1;
const int LOOP = 2;
const int CLAMP = 3;
const int MIRROR = 4;

void main(void)
{
    vec2 coord = (vTextureCoord * filterArea.xy) / dimensions;

    if (coord.x > 1.0 || coord.y > 1.0) {
        return;
    }

    float cx = coord.x - 0.5;
    float cy = (coord.y - 0.5) * aspect;
    float ny = (-sinDir * cx + cosDir * cy) / aspect + 0.5;

    // displacementMap: repeat
    // ny = ny > 1.0 ? ny - 1.0 : (ny < 0.0 ? 1.0 + ny : ny);

    // displacementMap: mirror
    ny = ny > 1.0 ? 2.0 - ny : (ny < 0.0 ? -ny : ny);

    vec4 dc = texture2D(displacementMap, vec2(0.5, ny));

    float displacement = (dc.r - dc.g) * (offset / filterArea.x);

    coord = vTextureCoord + vec2(cosDir * displacement, sinDir * displacement * aspect);

    if (fillMode == CLAMP) {
        coord = clamp(coord, filterClamp.xy, filterClamp.zw);
    } else {
        if( coord.x > filterClamp.z ) {
            if (fillMode == TRANSPARENT) {
                discard;
            } else if (fillMode == LOOP) {
                coord.x -= filterClamp.z;
            } else if (fillMode == MIRROR) {
                coord.x = filterClamp.z * 2.0 - coord.x;
            }
        } else if( coord.x < filterClamp.x ) {
            if (fillMode == TRANSPARENT) {
                discard;
            } else if (fillMode == LOOP) {
                coord.x += filterClamp.z;
            } else if (fillMode == MIRROR) {
                coord.x *= -filterClamp.z;
            }
        }

        if( coord.y > filterClamp.w ) {
            if (fillMode == TRANSPARENT) {
                discard;
            } else if (fillMode == LOOP) {
                coord.y -= filterClamp.w;
            } else if (fillMode == MIRROR) {
                coord.y = filterClamp.w * 2.0 - coord.y;
            }
        } else if( coord.y < filterClamp.y ) {
            if (fillMode == TRANSPARENT) {
                discard;
            } else if (fillMode == LOOP) {
                coord.y += filterClamp.w;
            } else if (fillMode == MIRROR) {
                coord.y *= -filterClamp.w;
            }
        }
    }

    gl_FragColor.r = texture2D(uSampler, coord + red * (1.0 - seed * 0.4) / filterArea.xy).r;
    gl_FragColor.g = texture2D(uSampler, coord + green * (1.0 - seed * 0.3) / filterArea.xy).g;
    gl_FragColor.b = texture2D(uSampler, coord + blue * (1.0 - seed * 0.2) / filterArea.xy).b;
    gl_FragColor.a = texture2D(uSampler, coord).a;
}
`;(function(e){Vt(t,e);function t(n){var r=e.call(this,Ht,Ut)||this;return r.offset=100,r.fillMode=t.TRANSPARENT,r.average=!1,r.seed=0,r.minSize=8,r.sampleSize=512,r._slices=0,r._offsets=new Float32Array(1),r._sizes=new Float32Array(1),r._direction=-1,r.uniforms.dimensions=new Float32Array(2),r._canvas=document.createElement(`canvas`),r._canvas.width=4,r._canvas.height=r.sampleSize,r.texture=L.from(r._canvas,{scaleMode:N.NEAREST}),Object.assign(r,t.defaults,n),r}return t.prototype.apply=function(e,t,n,r){var i=t.filterFrame,a=i.width,o=i.height;this.uniforms.dimensions[0]=a,this.uniforms.dimensions[1]=o,this.uniforms.aspect=o/a,this.uniforms.seed=this.seed,this.uniforms.offset=this.offset,this.uniforms.fillMode=this.fillMode,e.applyFilter(this,t,n,r)},t.prototype._randomizeSizes=function(){var e=this._sizes,t=this._slices-1,n=this.sampleSize,r=Math.min(this.minSize/n,.9/this._slices);if(this.average){for(var i=this._slices,a=1,o=0;o<t;o++){var s=a/(i-o),c=Math.max(s*(1-Math.random()*.6),r);e[o]=c,a-=c}e[t]=a}else{for(var a=1,l=Math.sqrt(1/this._slices),o=0;o<t;o++){var c=Math.max(l*a*Math.random(),r);e[o]=c,a-=c}e[t]=a}this.shuffle()},t.prototype.shuffle=function(){for(var e=this._sizes,t=this._slices-1;t>0;t--){var n=Math.random()*t>>0,r=e[t];e[t]=e[n],e[n]=r}},t.prototype._randomizeOffsets=function(){for(var e=0;e<this._slices;e++)this._offsets[e]=Math.random()*(Math.random()<.5?-1:1)},t.prototype.refresh=function(){this._randomizeSizes(),this._randomizeOffsets(),this.redraw()},t.prototype.redraw=function(){var e=this.sampleSize,t=this.texture,n=this._canvas.getContext(`2d`);n.clearRect(0,0,8,e);for(var r,i=0,a=0;a<this._slices;a++){r=Math.floor(this._offsets[a]*256);var o=this._sizes[a]*e,s=r>0?r:0,c=r<0?-r:0;n.fillStyle=`rgba(`+s+`, `+c+`, 0, 1)`,n.fillRect(0,i>>0,e,o+1>>0),i+=o}t.baseTexture.update(),this.uniforms.displacementMap=t},Object.defineProperty(t.prototype,`sizes`,{get:function(){return this._sizes},set:function(e){for(var t=Math.min(this._slices,e.length),n=0;n<t;n++)this._sizes[n]=e[n]},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`offsets`,{get:function(){return this._offsets},set:function(e){for(var t=Math.min(this._slices,e.length),n=0;n<t;n++)this._offsets[n]=e[n]},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`slices`,{get:function(){return this._slices},set:function(e){this._slices!==e&&(this._slices=e,this.uniforms.slices=e,this._sizes=this.uniforms.slicesWidth=new Float32Array(e),this._offsets=this.uniforms.slicesOffset=new Float32Array(e),this.refresh())},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`direction`,{get:function(){return this._direction},set:function(e){if(this._direction!==e){this._direction=e;var t=e*I;this.uniforms.sinDir=Math.sin(t),this.uniforms.cosDir=Math.cos(t)}},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`red`,{get:function(){return this.uniforms.red},set:function(e){this.uniforms.red=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`green`,{get:function(){return this.uniforms.green},set:function(e){this.uniforms.green=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blue`,{get:function(){return this.uniforms.blue},set:function(e){this.uniforms.blue=e},enumerable:!1,configurable:!0}),t.prototype.destroy=function(){var e;(e=this.texture)==null||e.destroy(!0),this.texture=this._canvas=this.red=this.green=this.blue=this._sizes=this._offsets=null},t.defaults={slices:5,offset:100,direction:0,fillMode:0,average:!1,seed:0,red:[0,0],green:[0,0],blue:[0,0],minSize:8,sampleSize:512},t.TRANSPARENT=0,t.ORIGINAL=1,t.LOOP=2,t.CLAMP=3,t.MIRROR=4,t})(R);var Wt=function(e,t){return Wt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Wt(e,t)};function Gt(e,t){Wt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Kt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,qt=`varying vec2 vTextureCoord;
varying vec4 vColor;

uniform sampler2D uSampler;

uniform float outerStrength;
uniform float innerStrength;

uniform vec4 glowColor;

uniform vec4 filterArea;
uniform vec4 filterClamp;
uniform bool knockout;

const float PI = 3.14159265358979323846264;

const float DIST = __DIST__;
const float ANGLE_STEP_SIZE = min(__ANGLE_STEP_SIZE__, PI * 2.0);
const float ANGLE_STEP_NUM = ceil(PI * 2.0 / ANGLE_STEP_SIZE);

const float MAX_TOTAL_ALPHA = ANGLE_STEP_NUM * DIST * (DIST + 1.0) / 2.0;

void main(void) {
    vec2 px = vec2(1.0 / filterArea.x, 1.0 / filterArea.y);

    float totalAlpha = 0.0;

    vec2 direction;
    vec2 displaced;
    vec4 curColor;

    for (float angle = 0.0; angle < PI * 2.0; angle += ANGLE_STEP_SIZE) {
       direction = vec2(cos(angle), sin(angle)) * px;

       for (float curDistance = 0.0; curDistance < DIST; curDistance++) {
           displaced = clamp(vTextureCoord + direction * 
                   (curDistance + 1.0), filterClamp.xy, filterClamp.zw);

           curColor = texture2D(uSampler, displaced);

           totalAlpha += (DIST - curDistance) * curColor.a;
       }
    }
    
    curColor = texture2D(uSampler, vTextureCoord);

    float alphaRatio = (totalAlpha / MAX_TOTAL_ALPHA);

    float innerGlowAlpha = (1.0 - alphaRatio) * innerStrength * curColor.a;
    float innerGlowStrength = min(1.0, innerGlowAlpha);
    
    vec4 innerColor = mix(curColor, glowColor, innerGlowStrength);

    float outerGlowAlpha = alphaRatio * outerStrength * (1. - curColor.a);
    float outerGlowStrength = min(1.0 - innerColor.a, outerGlowAlpha);

    vec4 outerGlowColor = outerGlowStrength * glowColor.rgba;
    
    if (knockout) {
      float resultAlpha = outerGlowAlpha + innerGlowAlpha;
      gl_FragColor = vec4(glowColor.rgb * resultAlpha, resultAlpha);
    }
    else {
      gl_FragColor = innerColor + outerGlowColor;
    }
}
`;(function(e){Gt(t,e);function t(n){var r=this,i=Object.assign({},t.defaults,n),a=i.outerStrength,o=i.innerStrength,s=i.color,c=i.knockout,l=i.quality,u=Math.round(i.distance);return r=e.call(this,Kt,qt.replace(/__ANGLE_STEP_SIZE__/gi,``+(1/l/u).toFixed(7)).replace(/__DIST__/gi,u.toFixed(0)+`.0`))||this,r.uniforms.glowColor=new Float32Array([0,0,0,1]),Object.assign(r,{color:s,outerStrength:a,innerStrength:o,padding:u,knockout:c}),r}return Object.defineProperty(t.prototype,`color`,{get:function(){return V(this.uniforms.glowColor)},set:function(e){z(e,this.uniforms.glowColor)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`outerStrength`,{get:function(){return this.uniforms.outerStrength},set:function(e){this.uniforms.outerStrength=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`innerStrength`,{get:function(){return this.uniforms.innerStrength},set:function(e){this.uniforms.innerStrength=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`knockout`,{get:function(){return this.uniforms.knockout},set:function(e){this.uniforms.knockout=e},enumerable:!1,configurable:!0}),t.defaults={distance:10,outerStrength:4,innerStrength:0,color:16777215,quality:.1,knockout:!1},t})(R);var Jt=function(e,t){return Jt=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Jt(e,t)};function Yt(e,t){Jt(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Xt=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Zt=`vec3 mod289(vec3 x)
{
    return x - floor(x * (1.0 / 289.0)) * 289.0;
}
vec4 mod289(vec4 x)
{
    return x - floor(x * (1.0 / 289.0)) * 289.0;
}
vec4 permute(vec4 x)
{
    return mod289(((x * 34.0) + 1.0) * x);
}
vec4 taylorInvSqrt(vec4 r)
{
    return 1.79284291400159 - 0.85373472095314 * r;
}
vec3 fade(vec3 t)
{
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}
// Classic Perlin noise, periodic variant
float pnoise(vec3 P, vec3 rep)
{
    vec3 Pi0 = mod(floor(P), rep); // Integer part, modulo period
    vec3 Pi1 = mod(Pi0 + vec3(1.0), rep); // Integer part + 1, mod period
    Pi0 = mod289(Pi0);
    Pi1 = mod289(Pi1);
    vec3 Pf0 = fract(P); // Fractional part for interpolation
    vec3 Pf1 = Pf0 - vec3(1.0); // Fractional part - 1.0
    vec4 ix = vec4(Pi0.x, Pi1.x, Pi0.x, Pi1.x);
    vec4 iy = vec4(Pi0.yy, Pi1.yy);
    vec4 iz0 = Pi0.zzzz;
    vec4 iz1 = Pi1.zzzz;
    vec4 ixy = permute(permute(ix) + iy);
    vec4 ixy0 = permute(ixy + iz0);
    vec4 ixy1 = permute(ixy + iz1);
    vec4 gx0 = ixy0 * (1.0 / 7.0);
    vec4 gy0 = fract(floor(gx0) * (1.0 / 7.0)) - 0.5;
    gx0 = fract(gx0);
    vec4 gz0 = vec4(0.5) - abs(gx0) - abs(gy0);
    vec4 sz0 = step(gz0, vec4(0.0));
    gx0 -= sz0 * (step(0.0, gx0) - 0.5);
    gy0 -= sz0 * (step(0.0, gy0) - 0.5);
    vec4 gx1 = ixy1 * (1.0 / 7.0);
    vec4 gy1 = fract(floor(gx1) * (1.0 / 7.0)) - 0.5;
    gx1 = fract(gx1);
    vec4 gz1 = vec4(0.5) - abs(gx1) - abs(gy1);
    vec4 sz1 = step(gz1, vec4(0.0));
    gx1 -= sz1 * (step(0.0, gx1) - 0.5);
    gy1 -= sz1 * (step(0.0, gy1) - 0.5);
    vec3 g000 = vec3(gx0.x, gy0.x, gz0.x);
    vec3 g100 = vec3(gx0.y, gy0.y, gz0.y);
    vec3 g010 = vec3(gx0.z, gy0.z, gz0.z);
    vec3 g110 = vec3(gx0.w, gy0.w, gz0.w);
    vec3 g001 = vec3(gx1.x, gy1.x, gz1.x);
    vec3 g101 = vec3(gx1.y, gy1.y, gz1.y);
    vec3 g011 = vec3(gx1.z, gy1.z, gz1.z);
    vec3 g111 = vec3(gx1.w, gy1.w, gz1.w);
    vec4 norm0 = taylorInvSqrt(vec4(dot(g000, g000), dot(g010, g010), dot(g100, g100), dot(g110, g110)));
    g000 *= norm0.x;
    g010 *= norm0.y;
    g100 *= norm0.z;
    g110 *= norm0.w;
    vec4 norm1 = taylorInvSqrt(vec4(dot(g001, g001), dot(g011, g011), dot(g101, g101), dot(g111, g111)));
    g001 *= norm1.x;
    g011 *= norm1.y;
    g101 *= norm1.z;
    g111 *= norm1.w;
    float n000 = dot(g000, Pf0);
    float n100 = dot(g100, vec3(Pf1.x, Pf0.yz));
    float n010 = dot(g010, vec3(Pf0.x, Pf1.y, Pf0.z));
    float n110 = dot(g110, vec3(Pf1.xy, Pf0.z));
    float n001 = dot(g001, vec3(Pf0.xy, Pf1.z));
    float n101 = dot(g101, vec3(Pf1.x, Pf0.y, Pf1.z));
    float n011 = dot(g011, vec3(Pf0.x, Pf1.yz));
    float n111 = dot(g111, Pf1);
    vec3 fade_xyz = fade(Pf0);
    vec4 n_z = mix(vec4(n000, n100, n010, n110), vec4(n001, n101, n011, n111), fade_xyz.z);
    vec2 n_yz = mix(n_z.xy, n_z.zw, fade_xyz.y);
    float n_xyz = mix(n_yz.x, n_yz.y, fade_xyz.x);
    return 2.2 * n_xyz;
}
float turb(vec3 P, vec3 rep, float lacunarity, float gain)
{
    float sum = 0.0;
    float sc = 1.0;
    float totalgain = 1.0;
    for (float i = 0.0; i < 6.0; i++)
    {
        sum += totalgain * pnoise(P * sc, rep);
        sc *= lacunarity;
        totalgain *= gain;
    }
    return abs(sum);
}
`,Qt=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;
uniform vec2 dimensions;

uniform vec2 light;
uniform bool parallel;
uniform float aspect;

uniform float gain;
uniform float lacunarity;
uniform float time;
uniform float alpha;

\${perlin}

void main(void) {
    vec2 coord = vTextureCoord * filterArea.xy / dimensions.xy;

    float d;

    if (parallel) {
        float _cos = light.x;
        float _sin = light.y;
        d = (_cos * coord.x) + (_sin * coord.y * aspect);
    } else {
        float dx = coord.x - light.x / dimensions.x;
        float dy = (coord.y - light.y / dimensions.y) * aspect;
        float dis = sqrt(dx * dx + dy * dy) + 0.00001;
        d = dy / dis;
    }

    vec3 dir = vec3(d, d, 0.0);

    float noise = turb(dir + vec3(time, 0.0, 62.1 + time) * 0.05, vec3(480.0, 320.0, 480.0), lacunarity, gain);
    noise = mix(noise, 0.0, 0.3);
    //fade vertically.
    vec4 mist = vec4(noise, noise, noise, 1.0) * (1.0 - coord.y);
    mist.a = 1.0;
    // apply user alpha
    mist *= alpha;

    gl_FragColor = texture2D(uSampler, vTextureCoord) + mist;

}
`;(function(e){Yt(t,e);function t(n){var r=e.call(this,Xt,Qt.replace("${perlin}",Zt))||this;r.parallel=!0,r.time=0,r._angle=0,r.uniforms.dimensions=new Float32Array(2);var i=Object.assign(t.defaults,n);return r._angleLight=new F,r.angle=i.angle,r.gain=i.gain,r.lacunarity=i.lacunarity,r.alpha=i.alpha,r.parallel=i.parallel,r.center=i.center,r.time=i.time,r}return t.prototype.apply=function(e,t,n,r){var i=t.filterFrame,a=i.width,o=i.height;this.uniforms.light=this.parallel?this._angleLight:this.center,this.uniforms.parallel=this.parallel,this.uniforms.dimensions[0]=a,this.uniforms.dimensions[1]=o,this.uniforms.aspect=o/a,this.uniforms.time=this.time,this.uniforms.alpha=this.alpha,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`angle`,{get:function(){return this._angle},set:function(e){this._angle=e;var t=e*I;this._angleLight.x=Math.cos(t),this._angleLight.y=Math.sin(t)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`gain`,{get:function(){return this.uniforms.gain},set:function(e){this.uniforms.gain=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`lacunarity`,{get:function(){return this.uniforms.lacunarity},set:function(e){this.uniforms.lacunarity=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`alpha`,{get:function(){return this.uniforms.alpha},set:function(e){this.uniforms.alpha=e},enumerable:!1,configurable:!0}),t.defaults={angle:30,gain:.5,lacunarity:2.5,time:0,parallel:!0,center:[0,0],alpha:1},t})(R);var $t=function(e,t){return $t=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},$t(e,t)};function en(e,t){$t(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var tn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,nn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;

uniform vec2 uVelocity;
uniform int uKernelSize;
uniform float uOffset;

const int MAX_KERNEL_SIZE = 2048;

// Notice:
// the perfect way:
//    int kernelSize = min(uKernelSize, MAX_KERNELSIZE);
// BUT in real use-case , uKernelSize < MAX_KERNELSIZE almost always.
// So use uKernelSize directly.

void main(void)
{
    vec4 color = texture2D(uSampler, vTextureCoord);

    if (uKernelSize == 0)
    {
        gl_FragColor = color;
        return;
    }

    vec2 velocity = uVelocity / filterArea.xy;
    float offset = -uOffset / length(uVelocity) - 0.5;
    int k = uKernelSize - 1;

    for(int i = 0; i < MAX_KERNEL_SIZE - 1; i++) {
        if (i == k) {
            break;
        }
        vec2 bias = velocity * (float(i) / float(k) + offset);
        color += texture2D(uSampler, vTextureCoord + bias);
    }
    gl_FragColor = color / float(uKernelSize);
}
`;(function(e){en(t,e);function t(t,n,r){t===void 0&&(t=[0,0]),n===void 0&&(n=5),r===void 0&&(r=0);var i=e.call(this,tn,nn)||this;return i.kernelSize=5,i.uniforms.uVelocity=new Float32Array(2),i._velocity=new le(i.velocityChanged,i),i.setVelocity(t),i.kernelSize=n,i.offset=r,i}return t.prototype.apply=function(e,t,n,r){var i=this.velocity,a=i.x,o=i.y;this.uniforms.uKernelSize=a!==0||o!==0?this.kernelSize:0,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`velocity`,{get:function(){return this._velocity},set:function(e){this.setVelocity(e)},enumerable:!1,configurable:!0}),t.prototype.setVelocity=function(e){if(Array.isArray(e)){var t=e[0],n=e[1];this._velocity.set(t,n)}else this._velocity.copyFrom(e)},t.prototype.velocityChanged=function(){this.uniforms.uVelocity[0]=this._velocity.x,this.uniforms.uVelocity[1]=this._velocity.y,this.padding=(Math.max(Math.abs(this._velocity.x),Math.abs(this._velocity.y))>>0)+1},Object.defineProperty(t.prototype,`offset`,{get:function(){return this.uniforms.uOffset},set:function(e){this.uniforms.uOffset=e},enumerable:!1,configurable:!0}),t})(R);var rn=function(e,t){return rn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},rn(e,t)};function an(e,t){rn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var on=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,sn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform float epsilon;

const int MAX_COLORS = %maxColors%;

uniform vec3 originalColors[MAX_COLORS];
uniform vec3 targetColors[MAX_COLORS];

void main(void)
{
    gl_FragColor = texture2D(uSampler, vTextureCoord);

    float alpha = gl_FragColor.a;
    if (alpha < 0.0001)
    {
      return;
    }

    vec3 color = gl_FragColor.rgb / alpha;

    for(int i = 0; i < MAX_COLORS; i++)
    {
      vec3 origColor = originalColors[i];
      if (origColor.r < 0.0)
      {
        break;
      }
      vec3 colorDiff = origColor - color;
      if (length(colorDiff) < epsilon)
      {
        vec3 targetColor = targetColors[i];
        gl_FragColor = vec4((targetColor + colorDiff) * alpha, alpha);
        return;
      }
    }
}
`;(function(e){an(t,e);function t(t,n,r){n===void 0&&(n=.05),r===void 0&&(r=t.length);var i=e.call(this,on,sn.replace(/%maxColors%/g,r.toFixed(0)))||this;return i._replacements=[],i._maxColors=0,i.epsilon=n,i._maxColors=r,i.uniforms.originalColors=new Float32Array(r*3),i.uniforms.targetColors=new Float32Array(r*3),i.replacements=t,i}return Object.defineProperty(t.prototype,`replacements`,{get:function(){return this._replacements},set:function(e){var t=this.uniforms.originalColors,n=this.uniforms.targetColors,r=e.length;if(r>this._maxColors)throw Error(`Length of replacements (`+r+`) exceeds the maximum colors length (`+this._maxColors+`)`);t[r*3]=-1;for(var i=0;i<r;i++){var a=e[i],o=a[0];typeof o==`number`?o=z(o):a[0]=V(o),t[i*3]=o[0],t[i*3+1]=o[1],t[i*3+2]=o[2];var s=a[1];typeof s==`number`?s=z(s):a[1]=V(s),n[i*3]=s[0],n[i*3+1]=s[1],n[i*3+2]=s[2]}this._replacements=e},enumerable:!1,configurable:!0}),t.prototype.refresh=function(){this.replacements=this._replacements},Object.defineProperty(t.prototype,`maxColors`,{get:function(){return this._maxColors},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`epsilon`,{get:function(){return this.uniforms.epsilon},set:function(e){this.uniforms.epsilon=e},enumerable:!1,configurable:!0}),t})(R);var cn=function(e,t){return cn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},cn(e,t)};function ln(e,t){cn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var un=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,dn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;
uniform vec2 dimensions;

uniform float sepia;
uniform float noise;
uniform float noiseSize;
uniform float scratch;
uniform float scratchDensity;
uniform float scratchWidth;
uniform float vignetting;
uniform float vignettingAlpha;
uniform float vignettingBlur;
uniform float seed;

const float SQRT_2 = 1.414213;
const vec3 SEPIA_RGB = vec3(112.0 / 255.0, 66.0 / 255.0, 20.0 / 255.0);

float rand(vec2 co) {
    return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
}

vec3 Overlay(vec3 src, vec3 dst)
{
    // if (dst <= 0.5) then: 2 * src * dst
    // if (dst > 0.5) then: 1 - 2 * (1 - dst) * (1 - src)
    return vec3((dst.x <= 0.5) ? (2.0 * src.x * dst.x) : (1.0 - 2.0 * (1.0 - dst.x) * (1.0 - src.x)),
                (dst.y <= 0.5) ? (2.0 * src.y * dst.y) : (1.0 - 2.0 * (1.0 - dst.y) * (1.0 - src.y)),
                (dst.z <= 0.5) ? (2.0 * src.z * dst.z) : (1.0 - 2.0 * (1.0 - dst.z) * (1.0 - src.z)));
}


void main()
{
    gl_FragColor = texture2D(uSampler, vTextureCoord);
    vec3 color = gl_FragColor.rgb;

    if (sepia > 0.0)
    {
        float gray = (color.x + color.y + color.z) / 3.0;
        vec3 grayscale = vec3(gray);

        color = Overlay(SEPIA_RGB, grayscale);

        color = grayscale + sepia * (color - grayscale);
    }

    vec2 coord = vTextureCoord * filterArea.xy / dimensions.xy;

    if (vignetting > 0.0)
    {
        float outter = SQRT_2 - vignetting * SQRT_2;
        vec2 dir = vec2(vec2(0.5, 0.5) - coord);
        dir.y *= dimensions.y / dimensions.x;
        float darker = clamp((outter - length(dir) * SQRT_2) / ( 0.00001 + vignettingBlur * SQRT_2), 0.0, 1.0);
        color.rgb *= darker + (1.0 - darker) * (1.0 - vignettingAlpha);
    }

    if (scratchDensity > seed && scratch != 0.0)
    {
        float phase = seed * 256.0;
        float s = mod(floor(phase), 2.0);
        float dist = 1.0 / scratchDensity;
        float d = distance(coord, vec2(seed * dist, abs(s - seed * dist)));
        if (d < seed * 0.6 + 0.4)
        {
            highp float period = scratchDensity * 10.0;

            float xx = coord.x * period + phase;
            float aa = abs(mod(xx, 0.5) * 4.0);
            float bb = mod(floor(xx / 0.5), 2.0);
            float yy = (1.0 - bb) * aa + bb * (2.0 - aa);

            float kk = 2.0 * period;
            float dw = scratchWidth / dimensions.x * (0.75 + seed);
            float dh = dw * kk;

            float tine = (yy - (2.0 - dh));

            if (tine > 0.0) {
                float _sign = sign(scratch);

                tine = s * tine / period + scratch + 0.1;
                tine = clamp(tine + 1.0, 0.5 + _sign * 0.5, 1.5 + _sign * 0.5);

                color.rgb *= tine;
            }
        }
    }

    if (noise > 0.0 && noiseSize > 0.0)
    {
        vec2 pixelCoord = vTextureCoord.xy * filterArea.xy;
        pixelCoord.x = floor(pixelCoord.x / noiseSize);
        pixelCoord.y = floor(pixelCoord.y / noiseSize);
        // vec2 d = pixelCoord * noiseSize * vec2(1024.0 + seed * 512.0, 1024.0 - seed * 512.0);
        // float _noise = snoise(d) * 0.5;
        float _noise = rand(pixelCoord * noiseSize * seed) - 0.5;
        color += _noise * noise;
    }

    gl_FragColor.rgb = color;
}
`;(function(e){ln(t,e);function t(n,r){r===void 0&&(r=0);var i=e.call(this,un,dn)||this;return i.seed=0,i.uniforms.dimensions=new Float32Array(2),typeof n==`number`?(i.seed=n,n=void 0):i.seed=r,Object.assign(i,t.defaults,n),i}return t.prototype.apply=function(e,t,n,r){this.uniforms.dimensions[0]=t.filterFrame?.width,this.uniforms.dimensions[1]=t.filterFrame?.height,this.uniforms.seed=this.seed,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`sepia`,{get:function(){return this.uniforms.sepia},set:function(e){this.uniforms.sepia=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`noise`,{get:function(){return this.uniforms.noise},set:function(e){this.uniforms.noise=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`noiseSize`,{get:function(){return this.uniforms.noiseSize},set:function(e){this.uniforms.noiseSize=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`scratch`,{get:function(){return this.uniforms.scratch},set:function(e){this.uniforms.scratch=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`scratchDensity`,{get:function(){return this.uniforms.scratchDensity},set:function(e){this.uniforms.scratchDensity=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`scratchWidth`,{get:function(){return this.uniforms.scratchWidth},set:function(e){this.uniforms.scratchWidth=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`vignetting`,{get:function(){return this.uniforms.vignetting},set:function(e){this.uniforms.vignetting=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`vignettingAlpha`,{get:function(){return this.uniforms.vignettingAlpha},set:function(e){this.uniforms.vignettingAlpha=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`vignettingBlur`,{get:function(){return this.uniforms.vignettingBlur},set:function(e){this.uniforms.vignettingBlur=e},enumerable:!1,configurable:!0}),t.defaults={sepia:.3,noise:.3,noiseSize:1,scratch:.5,scratchDensity:.3,scratchWidth:1,vignetting:.3,vignettingAlpha:1,vignettingBlur:.3},t})(R);var fn=function(e,t){return fn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},fn(e,t)};function pn(e,t){fn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var mn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,hn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform vec2 thickness;
uniform vec4 outlineColor;
uniform vec4 filterClamp;

const float DOUBLE_PI = 3.14159265358979323846264 * 2.;

void main(void) {
    vec4 ownColor = texture2D(uSampler, vTextureCoord);
    vec4 curColor;
    float maxAlpha = 0.;
    vec2 displaced;
    for (float angle = 0.; angle <= DOUBLE_PI; angle += \${angleStep}) {
        displaced.x = vTextureCoord.x + thickness.x * cos(angle);
        displaced.y = vTextureCoord.y + thickness.y * sin(angle);
        curColor = texture2D(uSampler, clamp(displaced, filterClamp.xy, filterClamp.zw));
        maxAlpha = max(maxAlpha, curColor.a);
    }
    float resultAlpha = max(maxAlpha, ownColor.a);
    gl_FragColor = vec4((ownColor.rgb + outlineColor.rgb * (1. - ownColor.a)) * resultAlpha, resultAlpha);
}
`;(function(e){pn(t,e);function t(n,r,i){n===void 0&&(n=1),r===void 0&&(r=0),i===void 0&&(i=.1);var a=e.call(this,mn,hn.replace(/\$\{angleStep\}/,t.getAngleStep(i)))||this;return a._thickness=1,a.uniforms.thickness=new Float32Array([0,0]),a.uniforms.outlineColor=new Float32Array([0,0,0,1]),Object.assign(a,{thickness:n,color:r,quality:i}),a}return t.getAngleStep=function(e){var n=Math.max(e*t.MAX_SAMPLES,t.MIN_SAMPLES);return(Math.PI*2/n).toFixed(7)},t.prototype.apply=function(e,t,n,r){this.uniforms.thickness[0]=this._thickness/t._frame.width,this.uniforms.thickness[1]=this._thickness/t._frame.height,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`color`,{get:function(){return V(this.uniforms.outlineColor)},set:function(e){z(e,this.uniforms.outlineColor)},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`thickness`,{get:function(){return this._thickness},set:function(e){this._thickness=e,this.padding=e},enumerable:!1,configurable:!0}),t.MIN_SAMPLES=1,t.MAX_SAMPLES=100,t})(R);var gn=function(e,t){return gn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},gn(e,t)};function _n(e,t){gn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var vn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,yn=`precision mediump float;

varying vec2 vTextureCoord;

uniform vec2 size;
uniform sampler2D uSampler;

uniform vec4 filterArea;

vec2 mapCoord( vec2 coord )
{
    coord *= filterArea.xy;
    coord += filterArea.zw;

    return coord;
}

vec2 unmapCoord( vec2 coord )
{
    coord -= filterArea.zw;
    coord /= filterArea.xy;

    return coord;
}

vec2 pixelate(vec2 coord, vec2 size)
{
	return floor( coord / size ) * size;
}

void main(void)
{
    vec2 coord = mapCoord(vTextureCoord);

    coord = pixelate(coord, size);

    coord = unmapCoord(coord);

    gl_FragColor = texture2D(uSampler, coord);
}
`;(function(e){_n(t,e);function t(t){t===void 0&&(t=10);var n=e.call(this,vn,yn)||this;return n.size=t,n}return Object.defineProperty(t.prototype,`size`,{get:function(){return this.uniforms.size},set:function(e){typeof e==`number`&&(e=[e,e]),this.uniforms.size=e},enumerable:!1,configurable:!0}),t})(R);var bn=function(e,t){return bn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},bn(e,t)};function xn(e,t){bn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Sn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Cn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;

uniform float uRadian;
uniform vec2 uCenter;
uniform float uRadius;
uniform int uKernelSize;

const int MAX_KERNEL_SIZE = 2048;

void main(void)
{
    vec4 color = texture2D(uSampler, vTextureCoord);

    if (uKernelSize == 0)
    {
        gl_FragColor = color;
        return;
    }

    float aspect = filterArea.y / filterArea.x;
    vec2 center = uCenter.xy / filterArea.xy;
    float gradient = uRadius / filterArea.x * 0.3;
    float radius = uRadius / filterArea.x - gradient * 0.5;
    int k = uKernelSize - 1;

    vec2 coord = vTextureCoord;
    vec2 dir = vec2(center - coord);
    float dist = length(vec2(dir.x, dir.y * aspect));

    float radianStep = uRadian;
    if (radius >= 0.0 && dist > radius) {
        float delta = dist - radius;
        float gap = gradient;
        float scale = 1.0 - abs(delta / gap);
        if (scale <= 0.0) {
            gl_FragColor = color;
            return;
        }
        radianStep *= scale;
    }
    radianStep /= float(k);

    float s = sin(radianStep);
    float c = cos(radianStep);
    mat2 rotationMatrix = mat2(vec2(c, -s), vec2(s, c));

    for(int i = 0; i < MAX_KERNEL_SIZE - 1; i++) {
        if (i == k) {
            break;
        }

        coord -= center;
        coord.y *= aspect;
        coord = rotationMatrix * coord;
        coord.y /= aspect;
        coord += center;

        vec4 sample = texture2D(uSampler, coord);

        // switch to pre-multiplied alpha to correctly blur transparent images
        // sample.rgb *= sample.a;

        color += sample;
    }

    gl_FragColor = color / float(uKernelSize);
}
`;(function(e){xn(t,e);function t(t,n,r,i){t===void 0&&(t=0),n===void 0&&(n=[0,0]),r===void 0&&(r=5),i===void 0&&(i=-1);var a=e.call(this,Sn,Cn)||this;return a._angle=0,a.angle=t,a.center=n,a.kernelSize=r,a.radius=i,a}return t.prototype.apply=function(e,t,n,r){this.uniforms.uKernelSize=this._angle===0?0:this.kernelSize,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`angle`,{get:function(){return this._angle},set:function(e){this._angle=e,this.uniforms.uRadian=e*Math.PI/180},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`center`,{get:function(){return this.uniforms.uCenter},set:function(e){this.uniforms.uCenter=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`radius`,{get:function(){return this.uniforms.uRadius},set:function(e){(e<0||e===1/0)&&(e=-1),this.uniforms.uRadius=e},enumerable:!1,configurable:!0}),t})(R);var wn=function(e,t){return wn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},wn(e,t)};function Tn(e,t){wn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var En=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Dn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;

uniform vec4 filterArea;
uniform vec4 filterClamp;
uniform vec2 dimensions;

uniform bool mirror;
uniform float boundary;
uniform vec2 amplitude;
uniform vec2 waveLength;
uniform vec2 alpha;
uniform float time;

float rand(vec2 co) {
    return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
}

void main(void)
{
    vec2 pixelCoord = vTextureCoord.xy * filterArea.xy;
    vec2 coord = pixelCoord / dimensions;

    if (coord.y < boundary) {
        gl_FragColor = texture2D(uSampler, vTextureCoord);
        return;
    }

    float k = (coord.y - boundary) / (1. - boundary + 0.0001);
    float areaY = boundary * dimensions.y / filterArea.y;
    float v = areaY + areaY - vTextureCoord.y;
    float y = mirror ? v : vTextureCoord.y;

    float _amplitude = ((amplitude.y - amplitude.x) * k + amplitude.x ) / filterArea.x;
    float _waveLength = ((waveLength.y - waveLength.x) * k + waveLength.x) / filterArea.y;
    float _alpha = (alpha.y - alpha.x) * k + alpha.x;

    float x = vTextureCoord.x + cos(v * 6.28 / _waveLength - time) * _amplitude;
    x = clamp(x, filterClamp.x, filterClamp.z);

    vec4 color = texture2D(uSampler, vec2(x, y));

    gl_FragColor = color * _alpha;
}
`;(function(e){Tn(t,e);function t(n){var r=e.call(this,En,Dn)||this;return r.time=0,r.uniforms.amplitude=new Float32Array(2),r.uniforms.waveLength=new Float32Array(2),r.uniforms.alpha=new Float32Array(2),r.uniforms.dimensions=new Float32Array(2),Object.assign(r,t.defaults,n),r}return t.prototype.apply=function(e,t,n,r){this.uniforms.dimensions[0]=t.filterFrame?.width,this.uniforms.dimensions[1]=t.filterFrame?.height,this.uniforms.time=this.time,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`mirror`,{get:function(){return this.uniforms.mirror},set:function(e){this.uniforms.mirror=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`boundary`,{get:function(){return this.uniforms.boundary},set:function(e){this.uniforms.boundary=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`amplitude`,{get:function(){return this.uniforms.amplitude},set:function(e){this.uniforms.amplitude[0]=e[0],this.uniforms.amplitude[1]=e[1]},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`waveLength`,{get:function(){return this.uniforms.waveLength},set:function(e){this.uniforms.waveLength[0]=e[0],this.uniforms.waveLength[1]=e[1]},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`alpha`,{get:function(){return this.uniforms.alpha},set:function(e){this.uniforms.alpha[0]=e[0],this.uniforms.alpha[1]=e[1]},enumerable:!1,configurable:!0}),t.defaults={mirror:!0,boundary:.5,amplitude:[0,20],waveLength:[30,100],alpha:[1,1],time:0},t})(R);var On=function(e,t){return On=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},On(e,t)};function kn(e,t){On(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var An=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,jn=`precision mediump float;

varying vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform vec4 filterArea;
uniform vec2 red;
uniform vec2 green;
uniform vec2 blue;

void main(void)
{
   gl_FragColor.r = texture2D(uSampler, vTextureCoord + red/filterArea.xy).r;
   gl_FragColor.g = texture2D(uSampler, vTextureCoord + green/filterArea.xy).g;
   gl_FragColor.b = texture2D(uSampler, vTextureCoord + blue/filterArea.xy).b;
   gl_FragColor.a = texture2D(uSampler, vTextureCoord).a;
}
`;(function(e){kn(t,e);function t(t,n,r){t===void 0&&(t=[-10,0]),n===void 0&&(n=[0,10]),r===void 0&&(r=[0,0]);var i=e.call(this,An,jn)||this;return i.red=t,i.green=n,i.blue=r,i}return Object.defineProperty(t.prototype,`red`,{get:function(){return this.uniforms.red},set:function(e){this.uniforms.red=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`green`,{get:function(){return this.uniforms.green},set:function(e){this.uniforms.green=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`blue`,{get:function(){return this.uniforms.blue},set:function(e){this.uniforms.blue=e},enumerable:!1,configurable:!0}),t})(R);var Mn=function(e,t){return Mn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Mn(e,t)};function Nn(e,t){Mn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Pn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Fn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;
uniform vec4 filterClamp;

uniform vec2 center;

uniform float amplitude;
uniform float wavelength;
// uniform float power;
uniform float brightness;
uniform float speed;
uniform float radius;

uniform float time;

const float PI = 3.14159;

void main()
{
    float halfWavelength = wavelength * 0.5 / filterArea.x;
    float maxRadius = radius / filterArea.x;
    float currentRadius = time * speed / filterArea.x;

    float fade = 1.0;

    if (maxRadius > 0.0) {
        if (currentRadius > maxRadius) {
            gl_FragColor = texture2D(uSampler, vTextureCoord);
            return;
        }
        fade = 1.0 - pow(currentRadius / maxRadius, 2.0);
    }

    vec2 dir = vec2(vTextureCoord - center / filterArea.xy);
    dir.y *= filterArea.y / filterArea.x;
    float dist = length(dir);

    if (dist <= 0.0 || dist < currentRadius - halfWavelength || dist > currentRadius + halfWavelength) {
        gl_FragColor = texture2D(uSampler, vTextureCoord);
        return;
    }

    vec2 diffUV = normalize(dir);

    float diff = (dist - currentRadius) / halfWavelength;

    float p = 1.0 - pow(abs(diff), 2.0);

    // float powDiff = diff * pow(p, 2.0) * ( amplitude * fade );
    float powDiff = 1.25 * sin(diff * PI) * p * ( amplitude * fade );

    vec2 offset = diffUV * powDiff / filterArea.xy;

    // Do clamp :
    vec2 coord = vTextureCoord + offset;
    vec2 clampedCoord = clamp(coord, filterClamp.xy, filterClamp.zw);
    vec4 color = texture2D(uSampler, clampedCoord);
    if (coord != clampedCoord) {
        color *= max(0.0, 1.0 - length(coord - clampedCoord));
    }

    // No clamp :
    // gl_FragColor = texture2D(uSampler, vTextureCoord + offset);

    color.rgb *= 1.0 + (brightness - 1.0) * p * fade;

    gl_FragColor = color;
}
`;(function(e){Nn(t,e);function t(n,r,i){n===void 0&&(n=[0,0]),i===void 0&&(i=0);var a=e.call(this,Pn,Fn)||this;return a.center=n,Object.assign(a,t.defaults,r),a.time=i,a}return t.prototype.apply=function(e,t,n,r){this.uniforms.time=this.time,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`center`,{get:function(){return this.uniforms.center},set:function(e){this.uniforms.center=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`amplitude`,{get:function(){return this.uniforms.amplitude},set:function(e){this.uniforms.amplitude=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`wavelength`,{get:function(){return this.uniforms.wavelength},set:function(e){this.uniforms.wavelength=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`brightness`,{get:function(){return this.uniforms.brightness},set:function(e){this.uniforms.brightness=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`speed`,{get:function(){return this.uniforms.speed},set:function(e){this.uniforms.speed=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`radius`,{get:function(){return this.uniforms.radius},set:function(e){this.uniforms.radius=e},enumerable:!1,configurable:!0}),t.defaults={amplitude:30,wavelength:160,brightness:1,speed:500,radius:-1},t})(R);var In=function(e,t){return In=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},In(e,t)};function Ln(e,t){In(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Rn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,zn=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform sampler2D uLightmap;
uniform vec4 filterArea;
uniform vec2 dimensions;
uniform vec4 ambientColor;
void main() {
    vec4 diffuseColor = texture2D(uSampler, vTextureCoord);
    vec2 lightCoord = (vTextureCoord * filterArea.xy) / dimensions;
    vec4 light = texture2D(uLightmap, lightCoord);
    vec3 ambient = ambientColor.rgb * ambientColor.a;
    vec3 intensity = ambient + light.rgb;
    vec3 finalColor = diffuseColor.rgb * intensity;
    gl_FragColor = vec4(finalColor, diffuseColor.a);
}
`;(function(e){Ln(t,e);function t(t,n,r){n===void 0&&(n=0),r===void 0&&(r=1);var i=e.call(this,Rn,zn)||this;return i._color=0,i.uniforms.dimensions=new Float32Array(2),i.uniforms.ambientColor=new Float32Array([0,0,0,r]),i.texture=t,i.color=n,i}return t.prototype.apply=function(e,t,n,r){this.uniforms.dimensions[0]=t.filterFrame?.width,this.uniforms.dimensions[1]=t.filterFrame?.height,e.applyFilter(this,t,n,r)},Object.defineProperty(t.prototype,`texture`,{get:function(){return this.uniforms.uLightmap},set:function(e){this.uniforms.uLightmap=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`color`,{get:function(){return this._color},set:function(e){var t=this.uniforms.ambientColor;typeof e==`number`?(z(e,t),this._color=e):(t[0]=e[0],t[1]=e[1],t[2]=e[2],t[3]=e[3],this._color=V(t))},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`alpha`,{get:function(){return this.uniforms.ambientColor[3]},set:function(e){this.uniforms.ambientColor[3]=e},enumerable:!1,configurable:!0}),t})(R);var Bn=function(e,t){return Bn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Bn(e,t)};function Vn(e,t){Bn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Hn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Un=`varying vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform float blur;
uniform float gradientBlur;
uniform vec2 start;
uniform vec2 end;
uniform vec2 delta;
uniform vec2 texSize;

float random(vec3 scale, float seed)
{
    return fract(sin(dot(gl_FragCoord.xyz + seed, scale)) * 43758.5453 + seed);
}

void main(void)
{
    vec4 color = vec4(0.0);
    float total = 0.0;

    float offset = random(vec3(12.9898, 78.233, 151.7182), 0.0);
    vec2 normal = normalize(vec2(start.y - end.y, end.x - start.x));
    float radius = smoothstep(0.0, 1.0, abs(dot(vTextureCoord * texSize - start, normal)) / gradientBlur) * blur;

    for (float t = -30.0; t <= 30.0; t++)
    {
        float percent = (t + offset - 0.5) / 30.0;
        float weight = 1.0 - abs(percent);
        vec4 sample = texture2D(uSampler, vTextureCoord + delta / texSize * percent * radius);
        sample.rgb *= sample.a;
        color += sample * weight;
        total += weight;
    }

    color /= total;
    color.rgb /= color.a + 0.00001;

    gl_FragColor = color;
}
`,Wn=function(e){Vn(t,e);function t(t,n,r,i){t===void 0&&(t=100),n===void 0&&(n=600);var a=e.call(this,Hn,Un)||this;return a.uniforms.blur=t,a.uniforms.gradientBlur=n,a.uniforms.start=r||new F(0,window.innerHeight/2),a.uniforms.end=i||new F(600,window.innerHeight/2),a.uniforms.delta=new F(30,30),a.uniforms.texSize=new F(window.innerWidth,window.innerHeight),a.updateDelta(),a}return t.prototype.updateDelta=function(){this.uniforms.delta.x=0,this.uniforms.delta.y=0},Object.defineProperty(t.prototype,`blur`,{get:function(){return this.uniforms.blur},set:function(e){this.uniforms.blur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`gradientBlur`,{get:function(){return this.uniforms.gradientBlur},set:function(e){this.uniforms.gradientBlur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`start`,{get:function(){return this.uniforms.start},set:function(e){this.uniforms.start=e,this.updateDelta()},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`end`,{get:function(){return this.uniforms.end},set:function(e){this.uniforms.end=e,this.updateDelta()},enumerable:!1,configurable:!0}),t}(R),Gn=function(e){Vn(t,e);function t(){return e!==null&&e.apply(this,arguments)||this}return t.prototype.updateDelta=function(){var e=this.uniforms.end.x-this.uniforms.start.x,t=this.uniforms.end.y-this.uniforms.start.y,n=Math.sqrt(e*e+t*t);this.uniforms.delta.x=e/n,this.uniforms.delta.y=t/n},t}(Wn),Kn=function(e){Vn(t,e);function t(){return e!==null&&e.apply(this,arguments)||this}return t.prototype.updateDelta=function(){var e=this.uniforms.end.x-this.uniforms.start.x,t=this.uniforms.end.y-this.uniforms.start.y,n=Math.sqrt(e*e+t*t);this.uniforms.delta.x=-t/n,this.uniforms.delta.y=e/n},t}(Wn);(function(e){Vn(t,e);function t(t,n,r,i){t===void 0&&(t=100),n===void 0&&(n=600);var a=e.call(this)||this;return a.tiltShiftXFilter=new Gn(t,n,r,i),a.tiltShiftYFilter=new Kn(t,n,r,i),a}return t.prototype.apply=function(e,t,n,r){var i=e.getFilterTexture();this.tiltShiftXFilter.apply(e,t,i,1),this.tiltShiftYFilter.apply(e,i,n,r),e.returnFilterTexture(i)},Object.defineProperty(t.prototype,`blur`,{get:function(){return this.tiltShiftXFilter.blur},set:function(e){this.tiltShiftXFilter.blur=this.tiltShiftYFilter.blur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`gradientBlur`,{get:function(){return this.tiltShiftXFilter.gradientBlur},set:function(e){this.tiltShiftXFilter.gradientBlur=this.tiltShiftYFilter.gradientBlur=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`start`,{get:function(){return this.tiltShiftXFilter.start},set:function(e){this.tiltShiftXFilter.start=this.tiltShiftYFilter.start=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`end`,{get:function(){return this.tiltShiftXFilter.end},set:function(e){this.tiltShiftXFilter.end=this.tiltShiftYFilter.end=e},enumerable:!1,configurable:!0}),t})(R);var qn=function(e,t){return qn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},qn(e,t)};function Jn(e,t){qn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}var Yn=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,Xn=`varying vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform float radius;
uniform float angle;
uniform vec2 offset;
uniform vec4 filterArea;

vec2 mapCoord( vec2 coord )
{
    coord *= filterArea.xy;
    coord += filterArea.zw;

    return coord;
}

vec2 unmapCoord( vec2 coord )
{
    coord -= filterArea.zw;
    coord /= filterArea.xy;

    return coord;
}

vec2 twist(vec2 coord)
{
    coord -= offset;

    float dist = length(coord);

    if (dist < radius)
    {
        float ratioDist = (radius - dist) / radius;
        float angleMod = ratioDist * ratioDist * angle;
        float s = sin(angleMod);
        float c = cos(angleMod);
        coord = vec2(coord.x * c - coord.y * s, coord.x * s + coord.y * c);
    }

    coord += offset;

    return coord;
}

void main(void)
{

    vec2 coord = mapCoord(vTextureCoord);

    coord = twist(coord);

    coord = unmapCoord(coord);

    gl_FragColor = texture2D(uSampler, coord );

}
`;(function(e){Jn(t,e);function t(n){var r=e.call(this,Yn,Xn)||this;return Object.assign(r,t.defaults,n),r}return Object.defineProperty(t.prototype,`offset`,{get:function(){return this.uniforms.offset},set:function(e){this.uniforms.offset=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`radius`,{get:function(){return this.uniforms.radius},set:function(e){this.uniforms.radius=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`angle`,{get:function(){return this.uniforms.angle},set:function(e){this.uniforms.angle=e},enumerable:!1,configurable:!0}),t.defaults={radius:200,angle:4,padding:20,offset:new F},t})(R);var Zn=function(e,t){return Zn=Object.setPrototypeOf||{__proto__:[]}instanceof Array&&function(e,t){e.__proto__=t}||function(e,t){for(var n in t)Object.prototype.hasOwnProperty.call(t,n)&&(e[n]=t[n])},Zn(e,t)};function Qn(e,t){Zn(e,t);function n(){this.constructor=e}e.prototype=t===null?Object.create(t):(n.prototype=t.prototype,new n)}function $n(e,t){var n={};for(var r in e)Object.prototype.hasOwnProperty.call(e,r)&&t.indexOf(r)<0&&(n[r]=e[r]);if(e!=null&&typeof Object.getOwnPropertySymbols==`function`)for(var i=0,r=Object.getOwnPropertySymbols(e);i<r.length;i++)t.indexOf(r[i])<0&&Object.prototype.propertyIsEnumerable.call(e,r[i])&&(n[r[i]]=e[r[i]]);return n}var er=`attribute vec2 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat3 projectionMatrix;

varying vec2 vTextureCoord;

void main(void)
{
    gl_Position = vec4((projectionMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
    vTextureCoord = aTextureCoord;
}`,tr=`varying vec2 vTextureCoord;
uniform sampler2D uSampler;
uniform vec4 filterArea;

uniform vec2 uCenter;
uniform float uStrength;
uniform float uInnerRadius;
uniform float uRadius;

const float MAX_KERNEL_SIZE = \${maxKernelSize};

// author: http://byteblacksmith.com/improvements-to-the-canonical-one-liner-glsl-rand-for-opengl-es-2-0/
highp float rand(vec2 co, float seed) {
    const highp float a = 12.9898, b = 78.233, c = 43758.5453;
    highp float dt = dot(co + seed, vec2(a, b)), sn = mod(dt, 3.14159);
    return fract(sin(sn) * c + seed);
}

void main() {

    float minGradient = uInnerRadius * 0.3;
    float innerRadius = (uInnerRadius + minGradient * 0.5) / filterArea.x;

    float gradient = uRadius * 0.3;
    float radius = (uRadius - gradient * 0.5) / filterArea.x;

    float countLimit = MAX_KERNEL_SIZE;

    vec2 dir = vec2(uCenter.xy / filterArea.xy - vTextureCoord);
    float dist = length(vec2(dir.x, dir.y * filterArea.y / filterArea.x));

    float strength = uStrength;

    float delta = 0.0;
    float gap;
    if (dist < innerRadius) {
        delta = innerRadius - dist;
        gap = minGradient;
    } else if (radius >= 0.0 && dist > radius) { // radius < 0 means it's infinity
        delta = dist - radius;
        gap = gradient;
    }

    if (delta > 0.0) {
        float normalCount = gap / filterArea.x;
        delta = (normalCount - delta) / normalCount;
        countLimit *= delta;
        strength *= delta;
        if (countLimit < 1.0)
        {
            gl_FragColor = texture2D(uSampler, vTextureCoord);
            return;
        }
    }

    // randomize the lookup values to hide the fixed number of samples
    float offset = rand(vTextureCoord, 0.0);

    float total = 0.0;
    vec4 color = vec4(0.0);

    dir *= strength;

    for (float t = 0.0; t < MAX_KERNEL_SIZE; t++) {
        float percent = (t + offset) / MAX_KERNEL_SIZE;
        float weight = 4.0 * (percent - percent * percent);
        vec2 p = vTextureCoord + dir * percent;
        vec4 sample = texture2D(uSampler, p);

        // switch to pre-multiplied alpha to correctly blur transparent images
        // sample.rgb *= sample.a;

        color += sample * weight;
        total += weight;

        if (t > countLimit){
            break;
        }
    }

    color /= total;
    // switch back from pre-multiplied alpha
    // color.rgb /= color.a + 0.00001;

    gl_FragColor = color;
}
`;(function(e){Qn(t,e);function t(n){var r=this,i=Object.assign(t.defaults,n),a=i.maxKernelSize,o=$n(i,[`maxKernelSize`]);return r=e.call(this,er,tr.replace("${maxKernelSize}",a.toFixed(1)))||this,Object.assign(r,o),r}return Object.defineProperty(t.prototype,`center`,{get:function(){return this.uniforms.uCenter},set:function(e){this.uniforms.uCenter=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`strength`,{get:function(){return this.uniforms.uStrength},set:function(e){this.uniforms.uStrength=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`innerRadius`,{get:function(){return this.uniforms.uInnerRadius},set:function(e){this.uniforms.uInnerRadius=e},enumerable:!1,configurable:!0}),Object.defineProperty(t.prototype,`radius`,{get:function(){return this.uniforms.uRadius},set:function(e){(e<0||e===1/0)&&(e=-1),this.uniforms.uRadius=e},enumerable:!1,configurable:!0}),t.defaults={strength:.1,center:[0,0],innerRadius:0,radius:-1,maxKernelSize:32},t})(R);var nr=`__NEIGHBOUR_RESIDENT_GAZE__`;function rr(e){let t=Reflect.get(globalThis,nr);if(!(!t||![t.x,t.y,t.at,e].every(Number.isFinite)||e<t.at||e-t.at>1200))return{x:Math.max(-1,Math.min(1,t.x)),y:Math.max(-1,Math.min(1,t.y))}}var ir=class{constructor(){this.reset()}reset(){this.position=void 0,this.lastAt=void 0}update(e,t){if(!Number.isFinite(t)||this.lastAt!==void 0&&t<this.lastAt){this.reset();return}let n=e&&[e.x,e.y].every(Number.isFinite);if(!n&&!this.position)return;let r=this.lastAt===void 0?16:Math.min(100,t-this.lastAt);this.lastAt=t;let i=1-Math.exp(-r/(n?75:220));this.position||={x:0,y:0};let a=n?{x:Math.max(-1,Math.min(1,e.x)),y:Math.max(-1,Math.min(1,e.y))}:{x:0,y:0};if(this.position.x+=(a.x-this.position.x)*i,this.position.y+=(a.y-this.position.y)*i,!n&&Math.hypot(this.position.x,this.position.y)<.001){this.reset();return}return{...this.position}}},ar={greeting:3200,listen:1700,speaking:2600,care:3300,explain:3600,agree:2200,thanks:2700,celebrate:3e3,idle:5800};function or(e){let t=Math.max(0,Math.min(1,e));return t*t*t*(10+t*(-15+6*t))}function Z(e,t,n,r,i){let a=or(Math.min(r/650,(i-r)/850));return{kind:e,action:a>0?t:`rest`,side:n,amount:a,sway:Math.sin(r/210)}}function sr(){let e,t,n=0,r=-1/0,i=-1/0;return{update(a,o,s=!1){e===void 0&&(e=a);let c=o&&ar[o.kind]&&Number.isFinite(o.start)&&a>=o.start&&(o.continuous||a-o.start<=o.duration);c&&(t?.kind!==o.kind||t?.start!==o.start||t?.continuous!==o.continuous)&&(t=o,n++,o.kind===`greeting`&&!o.continuous&&(i=-1/0)),c&&o.kind!==`idle`&&(r=a),c&&o.kind===`care`&&(i=a+6e4);let l=e=>({kind:e,action:`rest`,side:`right`,amount:0,sway:0});if(a<i)return l(`care`);let u=c?o.kind:`idle`,d=c?a-o.start:a-e,f=n%3==2?`left`:`right`;if(u===`listen`||u===`agree`)return l(u);if(u===`greeting`&&d<3600)return Z(u,`wave`,f,d,3600);if(u===`thanks`&&d<2700)return Z(u,`thanks`,f,d,2700);if(u===`celebrate`&&d<3e3)return Z(u,`celebrate`,`both`,d,3e3);if([`speaking`,`explain`].includes(u)||c&&o.continuous){let e=Math.floor(d/6800),t=d%6800,r=(e+n)%3==0?`beat`:`offer`;return t<2600&&(u===`explain`||e%3!=2)?Z(u,r,(e+n)%3==1?`left`:`right`,t,2600):l(u)}let p=a-e;if(p<3600&&r===-1/0)return Z(`greeting`,`wave`,`right`,p,3600);if(s||a-r<18e3)return l(u);let m=Math.floor(p/14e4),h=p%14e4;for(let[e,t]of[39e3,84e3,133e3].entries())if(h>=t&&h<t+3300)return Z(`idle`,`wave`,(m*3+e)%3==1?`left`:`right`,h-t,3300);return l(u)}}}function cr(e,t=!1,n=`0`,r){if(!Number.isFinite(e)||e<0)return;r||=t||e>=3600?{action:`rest`,amount:0}:Z(`greeting`,`wave`,`right`,e,3600);let i=r.side===`left`||r.side===`both`?r.amount:0,a=r.side===`right`||r.side===`both`?r.amount:0,o=(r.sway||0)*(t?.58:1),s=t?.58:1,c=r.action===`wave`,l={leftShoulder:[0,-.7*i*s,-.8*i*s],rightShoulder:[0,.7*a*s,.8*a*s],leftUpperArm:[-2*i,-3*i,72*(1-i)+30*i],rightUpperArm:[-2*a,3*a,-72*(1-a)-30*a],leftLowerArm:[55*i,-4*i,-5-135*i],rightLowerArm:[55*a,4*a,5+135*a],leftHand:[30*i,-4*i,-18*o*i],rightHand:[30*a,4*a,18*o*a]};if(!c)for(let[e,t,n]of[[`left`,i,1],[`right`,a,-1]]){let i=t*(r.action===`celebrate`?1:r.action===`beat`?.45:r.action===`thanks`?.35:.65);l[`${e}UpperArm`]=[-5*i,-3*n*i,n*(72-10*i)],l[`${e}LowerArm`]=[32*i,-60*n*i,-n*(5+48*i)],l[`${e}Hand`]=[15*i,-8*n*i,-n*4*o*i]}if(n===`1`)for(let e of Object.values(l))e[0]*=-1,e[2]*=-1;return l}function lr(e,t=!1,n){let r=cr(e,t,`0`,n);if(!r)return;let i=Math.max(0,Math.abs(r.leftLowerArm[2])-5)/135,a=Math.max(0,Math.abs(r.rightLowerArm[2])-5)/135;return{ParamArmLA:i*.85,ParamArmRA:a*.85,ParamHandL:r.leftHand[2]/18*.45,ParamHandR:r.rightHand[2]/18*.45,ParamShoulderL:i*.14,ParamShoulderR:a*.14}}function ur(e,t=`idle`,n=!1){if(!Number.isFinite(e)||e<0)return;let r=e/24e3*2*Math.PI,i=t===`care`?.38:t===`idle`?1:.55;return{x:n?0:Math.sin(r)*2.8*i,y:Math.sin(r*2+.4)*1.2*i,z:Math.sin(r+1.2)*1*i,body:Math.sin(r*.75)*1.1*i}}function dr(e,t){return e?.continuous&&[`greeting`,`agree`,`thanks`,`celebrate`].includes(e.kind)&&t-e.start>e.duration?{...e,kind:`speaking`,start:e.start+e.duration,duration:ar.speaking}:e}function fr(e,t){if(e=dr(e,t),!e||!ar[e.kind]||!Number.isFinite(t)||!Number.isFinite(e.start)||!Number.isFinite(e.duration)||e.duration<=0)return;let n=(t-e.start)/e.duration,r=e.continuous&&n>=0?n%1:n;if(r<0||r>1)return;let i=Math.max(0,Math.min(1,r/.18,(1-r)/.22)),a=e.kind===`greeting`?i*i*(3-2*i):Math.sin(Math.PI*r)**2,o=Math.sin(4*Math.PI*r);return e.kind===`idle`?{x:4.8*Math.sin(2*Math.PI*r)*a,y:.8*o*a,z:1.1*a,body:.8*Math.sin(2*Math.PI*r)*a}:e.kind===`thanks`?{x:0,y:-4.5*a,z:.4*a,body:0}:e.kind===`agree`?{x:0,y:3.8*o*a,z:0,body:0}:e.kind===`celebrate`?{x:.6*o*a,y:2.5*a,z:1.2*o*a,body:.8*o*a}:e.kind===`explain`?{x:2*Math.sin(2*Math.PI*r)*a,y:1.2*o*a,z:.6*a,body:.6*o*a}:e.kind===`greeting`?{x:1.4*a,y:4*o*a,z:2*a,body:.7*a}:e.kind===`listen`?{x:0,y:4*Math.sin(2*Math.PI*r)*a,z:.5*a,body:0}:e.kind===`care`?{x:-.7*a,y:1.4*o*a,z:1.3*a,body:.2*a}:{x:Math.sin(2*Math.PI*r)*a,y:1.5*o*a,z:.6*a,body:.25*a}}function pr(e,t){if(e=dr(e,t),!fr(e,t))return;let n=(t-e.start)/e.duration,r=e.continuous?n%1:n,i=Math.max(0,Math.min(1,r/.18,(1-r)/.22)),a=e.kind===`greeting`?i*i*(3-2*i):Math.sin(Math.PI*r)**2,o=Math.sin(6*Math.PI*r),s=(e.kind===`greeting`?.05:.25)*a,c=a;if([`speaking`,`explain`].includes(e.kind)){let e=Math.floor(n)%3;s=a*(e===1?1:e===2?.12:.25),c=a*(e===0?1:e===2?.12:.25)}let l=[`greeting`,`idle`].includes(e.kind),u=e.kind===`care`,d=e.kind===`listen`;(u||d)&&(s=c=a*(d?.35:.65)),(e.kind===`thanks`||e.kind===`agree`)&&(s=c=a*.35),e.kind===`celebrate`&&(s=c=a*.85);let f=l?48:8,p=l?8:u?110:75,m=l?110:15;return{spine:[(e.kind===`thanks`?4:d?2.2:u?1.5:.6)*a,.6*(s-c),.5*(c-s)],leftShoulder:[0,-1.3*s,-1.4*s],rightShoulder:[0,1.3*c,1.4*c],leftUpperArm:[-2*s,-4*s,-8*s],rightUpperArm:[-2*c,4*c,f*c],leftLowerArm:[0,-p*s,-m*s],rightLowerArm:[0,p*c,m*c],leftHand:[-14*s,-4*s,3*s],rightHand:[(l?-38:-14)*c,4*c,(l?10*o:-3)*c]}}function mr(e,t){e=dr(e,t);let n=pr(e,t);if(!n)return;let r=(t-e.start)/e.duration%1,i=[`greeting`,`idle`].includes(e.kind),a=n.rightUpperArm[2]/(i?48:8),o=-n.leftUpperArm[2]/8;return{ParamBodyAngleX:n.spine[1]/8,ParamBodyAngleY:n.spine[0]/12,ParamArmLA:o*.28,ParamArmRA:a*(i?.72:.3),ParamHandL:o*.18,ParamHandR:a*(i?.35*Math.sin(6*Math.PI*r):.18),ParamShoulderL:o*.12,ParamShoulderR:a*.15}}function hr(){let e=matchMedia(`(prefers-reduced-motion: reduce)`),t=!1,n,r,i,a=new Map,o=new Map,s,c=sr(),l=new ir;return u=>{r!==u.model&&(r=u.model,a.clear(),o.clear(),s=void 0,n=void 0,c=sr(),i=u.model.getModel?.()?.parameters);let d=Reflect.get(globalThis,`__NEIGHBOUR_RESIDENT_GESTURE__`),f=performance.now(),p=s===void 0?1/60:Math.max(0,Math.min(.05,(f-s)/1e3));s=f;let m=!document.hidden&&!e.matches?fr(d,performance.now()):void 0;(document.hidden||e.matches)&&l.reset();let h=!document.hidden&&!e.matches?l.update(rr(performance.now()),performance.now()):void 0,g=c.update(f,d,!!h),_=document.body?.dataset?.cloudView===`resident`&&!document.hidden&&!e.matches?lr(f,g.kind===`care`,g):void 0,v=_?{...m?mr(d,performance.now()):void 0,..._}:m?mr(d,performance.now()):void 0,y=_?ur(f,g.kind,!!h):void 0;for(let[e,t]of a)Math.abs(u.model.getParameterValueById(e)-t.after)<1e-6&&u.model.setParameterValueById(e,t.before);if(a.clear(),v||(o.clear(),s=void 0),i&&v)for(let[e,t]of Object.entries(v)){let n=e.replace(/^Param/,`PARAM_`).replace(/([a-z])([A-Z])/g,`$1_$2`).toUpperCase(),r=i.ids.includes(e)?e:n,s=i.ids.indexOf(r);if(s<0)continue;let c=i.minimumValues[s],l=i.maximumValues[s],d=u.model.getParameterValueById(r);if(![c,l,d,t].every(Number.isFinite)||l<=c)continue;let f=(l-c)*.08*Math.max(-1,Math.min(1,t)),m=o.get(r)||0,h=m+(f-m)*(1-Math.exp(-8*p));o.set(r,h);let g=Math.max(c,Math.min(l,d+h));u.model.setParameterValueById(r,g),a.set(r,{before:d,after:g})}if(!m&&!h&&!y&&!t)return;t=!!m||!!h||!!y;let b=u.modelParameters.value,x=e=>Math.max(-30,Math.min(30,e)),S=d?.kind===`idle`&&h?0:1;u.model.setParameterValueById(`ParamAngleX`,x((b.angleX||0)+(m?.x||0)*S+(y?.x||0)-(h?.x||0)*20)),u.model.setParameterValueById(`ParamAngleY`,x((b.angleY||0)+(m?.y||0)*S+(y?.y||0)-(h?.y||0)*13)),u.model.setParameterValueById(`ParamAngleZ`,x((b.angleZ||0)+(m?.z||0)+(y?.z||0))),u.model.setParameterValueById(`ParamBodyAngleZ`,x((b.bodyAngleZ||0)+(m?.body||0)+(y?.body||0))),h?(n||=[u.model.getParameterValueById(`ParamEyeBallX`),u.model.getParameterValueById(`ParamEyeBallY`)],u.model.setParameterValueById(`ParamEyeBallX`,-h.x*.85),u.model.setParameterValueById(`ParamEyeBallY`,-h.y*.6)):n&&=(u.model.setParameterValueById(`ParamEyeBallX`,n[0]),u.model.setParameterValueById(`ParamEyeBallY`,n[1]),void 0)}}var gr=e(me(),1);async function _r(e){let t=await gr.default.loadAsync(e),n=Object.keys(t.files),r={fileName:e.name||`live2d-model.zip`,totalFiles:n.length,status:`VALID`,entryPoint:null,structureType:`Unknown`,errors:[],warnings:[],checks:[]},i=n.filter(e=>e.endsWith(`.model3.json`));if(i.length>0)r.entryPoint=i[0],r.structureType=`Standard (model3.json)`,r.checks.push(`Entry point identified: ${r.entryPoint}`);else{let e=n.filter(e=>e.endsWith(`.moc3`));e.length===1?(r.structureType=`Heuristic (Loose Files)`,r.checks.push(`Heuristic match found: Unique MOC file ${e[0]}`)):r.errors.push(`Invalid Structure: No .model3.json found and ${e.length} .moc3 files encountered.`)}let a=n.find(e=>e.endsWith(`.moc3`));if(a){let e=await t.file(a).async(`uint8array`),n=String.fromCharCode(...e.slice(0,4)),i=e[4],o=e.length/1024/1024;r.mocInfo={header:n,ver:i,size:e.length},n===`MOC3`?r.checks.push(`MOC3 Header Valid (Sub-version: ${i}, Size: ${o.toFixed(2)} MB)`):r.errors.push(`Invalid MOC Header: "${n}" (Expected MOC3)`),o>100?r.errors.push(`CRITICAL WEIGHT: MOC file is ${o.toFixed(2)} MB. This "Mega-Model" likely exceeds browser WASM memory limits.`):o>30&&r.warnings.push(`HEAVY RESOURCE: MOC file is ${o.toFixed(2)} MB. This may cause performance issues in web browsers.`)}let o=new Map;n.forEach(e=>{if(e.endsWith(`/`))return;let t=e.split(/[\\/]/).pop();o.has(t)||o.set(t,[]),o.get(t).push(e)});for(let[e,t]of o.entries())t.length>1&&r.errors.push(`BASENAME COLLISION: Filename "${e}" exists in multiple locations: ${t.join(`, `)}. This causes data loss in AIRI's loader.`);if(r.entryPoint)try{let e=await t.file(r.entryPoint).async(`text`),i=JSON.parse(e),a=r.entryPoint.split(/[\\/]/).slice(0,-1).join(`/`),o=e=>{if(!e)return``;let t=a?[...a.split(`/`),...e.split(/[\\/]/)]:e.split(/[\\/]/),n=[];for(let e of t)e===`.`||e===``||(e===`..`?n.pop():n.push(e));return n.join(`/`)},s=(e,t)=>{let i=o(e);if(!n.includes(i)){let a=n.find(e=>e.toLowerCase()===i.toLowerCase());a?r.errors.push(`CASE SENSITIVITY MISMATCH: "${e}" expects "${i}" but ZIP contains "${a}". Browsers are case-sensitive.`):r.errors.push(`MISSING REFERENCE: ${t} "${e}" (expected at "${i}") not found in ZIP.`)}},c=i.FileReferences||{};c.Moc&&s(c.Moc,`MOC`),Array.isArray(c.Textures)&&c.Textures.forEach(e=>s(e,`Texture`)),c.Physics&&s(c.Physics,`Physics`),Array.isArray(c.Expressions)&&c.Expressions.forEach(e=>s(typeof e==`string`?e:e.File,`Expression`))}catch(e){r.errors.push(`JSON PARSE ERROR: Failed to parse ${r.entryPoint}: ${e.message}`)}return r.errors.length>0?r.status=`INVALID`:r.warnings.length>0?r.status=`WARNING`:r.status=`VALID`,r}function vr(){let e=-1,t,n=-1;function r(r,i){(i>=e||i<n)&&(t=[S.randFloat(-1,1),S.randFloat(-1,.7)],n=i,e=i+ye()/1e3,r.focusController.focus(t[0]*.5,t[1]*.5,!1)),r.focusController.update(i-n);let a=r.coreModel;a.setParameterValueById(`ParamEyeBallX`,S.lerp(a.getParameterValueById(`ParamEyeBallX`),t[0],.3)),a.setParameterValueById(`ParamEyeBallY`,S.lerp(a.getParameterValueById(`ParamEyeBallY`),t[1],.3))}return{update:r}}var yr={"punchy-v":{topYaw:10,topRoll:8,bottomDip:4,pattern:`v`},"balanced-v":{topYaw:6,topRoll:0,bottomDip:6,pattern:`v`},"swing-lr":{topYaw:8,topRoll:0,bottomDip:6,swingLift:8,pattern:`swing`},"sway-sine":{topYaw:10,topRoll:0,bottomDip:0,swingLift:10,pattern:`sway`}};function br(e){let{baseAngles:t,releaseDelayMs:n=1800,defaultIntervalMs:r=600,styles:i={},initialStyle:a=`punchy-v`,autoStyleShift:o=!1}=e,s={...yr,...i},c=y(0),l=y(0),u=y(0),d=y(0),f=y(0),p=y(0),m=y([]),h=y(`left`),g=y(!1),_=y(!1),v=y(null),x=y(null),S=y(null),C=y(a),w=y(o),T=b(()=>t());function E(e,t,n){return e+(t-e)*n}function ee(e){return 1-(1-e)**3}function D(){return s[C.value]||yr[`punchy-v`]}function O(e){let{topYaw:t,topRoll:n,swingLift:r,pattern:i}=D(),a=e===`left`?-1:1,o=i===`swing`||i===`sway`?r??n:n,s=T.value.z+(i===`swing`||i===`sway`?o:a*o);return{y:T.value.y+a*t,z:s}}function te(){let{bottomDip:e}=D();return{y:T.value.y,z:T.value.z-e}}function k(e){let t=l.value,r=u.value;for(!g.value&&!m.value.length&&(t=T.value.y,r=T.value.z),t??=T.value.y,r??=T.value.z;m.value.length;){let n=m.value[0];if(e<n.start){t=n.fromY,r=n.fromZ;break}let i=Math.min(1,(e-n.start)/Math.max(n.duration,1)),a=ee(i);if(t=E(n.fromY,n.toY,a),r=E(n.fromZ,n.toZ,a),i>=1){m.value.shift();continue}break}let i=v.value,a=g.value&&i!=null?e-i:1/0;g.value&&!m.value.length&&a>n&&(g.value=!1,_.value=!1,h.value=`left`,m.value=[],v.value=null,t=T.value.y,r=T.value.z,f.value*=.5,p.value*=.5),l.value=t,u.value=r}function A(e){let t=e!=null&&Number.isFinite(e)?Number(e):typeof performance<`u`?performance.now():Date.now();if(k(t),!g.value){g.value=!0,v.value=t;return}let n=Math.min(2e3,Math.max(220,v.value==null?r:t-v.value));if(v.value=t,x.value=n,S.value=S.value==null?n:S.value*.7+n*.3,w.value&&S.value){let e=6e4/S.value,t=e<120?`swing-lr`:e<180?`balanced-v`:`punchy-v`;t!==C.value&&(C.value=t)}let i=Math.max(80,n/2),a={y:l.value,z:u.value};m.value=[];let o=D(),s=h.value===`left`?`right`:`left`;if(o.pattern===`v`){if(!_.value){let e=O(`left`);m.value.push({start:t,duration:i,fromY:a.y,fromZ:a.z,toY:e.y,toZ:e.z}),_.value=!0,h.value=`left`;return}let e=te(),n=O(s);m.value.push({start:t,duration:i,fromY:a.y,fromZ:a.z,toY:e.y,toZ:e.z}),m.value.push({start:t+i,duration:i,fromY:e.y,fromZ:e.z,toY:n.y,toZ:n.z}),h.value=s}else if(o.pattern===`swing`){let e=h.value,r=O(e),i=O(s),o=Math.max(60,n*.35),c=Math.max(60,n-o);m.value.push({start:t,duration:o,fromY:a.y,fromZ:a.z,toY:r.y,toZ:r.z}),m.value.push({start:t+o,duration:c,fromY:r.y,fromZ:r.z,toY:i.y,toZ:i.z}),_.value=!0,h.value=s}else if(o.pattern===`sway`){let e=h.value,r=O(e),c=O(s),l={y:T.value.y,z:T.value.z},u=o.swingLift??10;if(!_.value){m.value.push({start:t,duration:i,fromY:a.y,fromZ:a.z,toY:r.y,toZ:r.z}),_.value=!0,h.value=e;return}let d={y:0,z:l.z+u},f=Math.max(60,n*.5),p=Math.max(60,n-f);m.value.push({start:t,duration:f,fromY:a.y,fromZ:a.z,toY:d.y,toZ:d.z}),m.value.push({start:t+f,duration:p,fromY:d.y,fromZ:d.z,toY:c.y,toZ:c.z}),_.value=!0,h.value=s}}return{targetX:c,targetY:l,targetZ:u,velocityX:d,velocityY:f,velocityZ:p,updateTargets:k,scheduleBeat:A,setStyle:e=>{C.value=e},getStyle:()=>C.value,setAutoStyleShift:e=>{w.value=e},debugState:()=>({primed:g.value,patternStarted:_.value,lastBeatTimestamp:v.value,lastInterval:x.value,avgInterval:S.value,bpm:S.value?6e4/S.value:null,style:C.value,segments:[...m.value]})}}function xr(e){return`expression-defaults:${e}`}function Sr(e){try{let t=localStorage.getItem(xr(e));return t?JSON.parse(t):null}catch{return null}}function Cr(e,t){try{localStorage.setItem(xr(e),JSON.stringify(t))}catch(e){console.warn(`[expression-store] Failed to persist defaults:`,e)}}var wr=w(`live2d-expressions`,()=>{let e=y(new Map),t=y(``),n=y(new Map),r=y(`none`),i=y(new Map);function a(){for(let t of e.value.values())t.resetTimer!=null&&(clearTimeout(t.resetTimer),t.resetTimer=void 0)}function o(e){return{name:e.name,value:e.currentValue,default:e.defaultValue,active:e.currentValue!==e.defaultValue,autoResetAt:e.resetTimer==null?void 0:Date.now()}}function s(){return Array.from(e.value.keys())}function c(r,i,o){a(),e.value=new Map,n.value=new Map,t.value=r;for(let e of i)n.value.set(e.name,e);for(let t of o)e.value.set(t.name,{...t});let s=Sr(r);if(s)for(let[t,n]of Object.entries(s)){let r=e.value.get(t);r&&(r.defaultValue=n,r.currentValue=n)}}function l(t){let r=n.value.get(t);if(r)return{kind:`group`,group:r};let i=e.value.get(t);return i?{kind:`param`,entry:i}:null}function u(t,n,r){let i=l(t);if(!i)return{success:!1,error:`Expression or parameter "${t}" not found.`,available:s()};let a=typeof n==`boolean`?+!!n:n;if(i.kind===`group`){let t=[];for(let n of i.group.parameters){let i=e.value.get(n.parameterId);i&&(b(i,a,r),t.push(o(i)))}return{success:!0,state:t}}return b(i.entry,a,r),{success:!0,state:o(i.entry)}}function d(t){if(!t){let t=[];for(let n of e.value.values())t.push(o(n));return{success:!0,state:t}}let n=l(t);if(!n)return{success:!1,error:`Expression or parameter "${t}" not found.`,available:s()};if(n.kind===`group`){let t=[];for(let r of n.group.parameters){let n=e.value.get(r.parameterId);n&&t.push(o(n))}return{success:!0,state:t}}return{success:!0,state:o(n.entry)}}function f(t,n){let r=l(t);if(!r)return{success:!1,error:`Expression or parameter "${t}" not found.`,available:s()};if(r.kind===`group`){let t=r.group.parameters.some(t=>{if(t.value===0)return!1;let n=e.value.get(t.parameterId);return n&&n.currentValue===t.value}),i=[];for(let a of r.group.parameters){let r=e.value.get(a.parameterId);r&&(b(r,t?r.modelDefault:a.value,n),i.push(o(r)))}return{success:!0,state:i}}let i=r.entry;return b(i,i.currentValue===i.modelDefault?i.targetValue:i.modelDefault,n),{success:!0,state:o(i)}}function p(){if(!t.value)return{success:!1,error:`No model loaded.`};let n={};for(let[t,r]of e.value)r.defaultValue=r.currentValue,n[t]=r.currentValue;return Cr(t.value,n),{success:!0}}function m(){a();let t=[];for(let n of e.value.values())n.currentValue=n.modelDefault,t.push(o(n));return{success:!0,state:t}}function h(){a(),e.value=new Map,n.value=new Map,r.value=`none`,i.value=new Map,t.value=``}function g(e){r.value=e}function _(e,t){i.value.set(e,t)}function v(e){return r.value===`all`?!0:r.value===`none`?!1:i.value.get(e)??!1}function b(e,t,n){if(e.resetTimer!=null&&(clearTimeout(e.resetTimer),e.resetTimer=void 0),e.currentValue=t,n&&n>0){let t=e.defaultValue;e.resetTimer=setTimeout(()=>{e.currentValue=t,e.resetTimer=void 0},n*1e3)}}return{expressions:e,modelId:t,expressionGroups:n,llmMode:r,llmExposed:i,registerExpressions:c,resolve:l,set:u,get:d,toggle:f,saveDefaults:p,resetAll:m,dispose:h,setLlmMode:g,setLlmExposed:_,isExposedToLlm:v}});function Tr(e){let t=wr(),n=new Set;async function r(n,r){let i=[],a=new Map;for(let e of n)try{let t=await r(e.File),n=JSON.parse(t),o=[];for(let e of n.Parameters){let t=l(e.Blend);if(o.push({parameterId:e.Id,blend:t,value:e.Value}),!a.has(e.Id)){let n=u(e.Id);a.set(e.Id,{name:e.Id,parameterId:e.Id,blend:t,currentValue:n,defaultValue:n,modelDefault:n,targetValue:e.Value})}else if(e.Value!==0){let t=a.get(e.Id);t.targetValue===0&&(t.targetValue=e.Value)}}i.push({name:e.Name,parameters:o})}catch(t){console.warn(`[expression-controller] Failed to parse exp3 for "${e.Name}" (${e.File}):`,t)}t.registerExpressions(e.modelId??`unknown`,i,Array.from(a.values()))}function i(e){let r=new Set;for(let n of t.expressions.values()){if(a(n))continue;let t=o(n,e);e.setParameterValueById(n.parameterId,t),r.add(n.parameterId)}for(let t of n)if(!r.has(t)){let n=s(t);n&&e.setParameterValueById(t,n.modelDefault)}n.clear();for(let e of r)n.add(e)}function a(e){switch(e.blend){case`Add`:return e.currentValue===0;case`Multiply`:return e.currentValue===1;default:return e.currentValue===e.modelDefault}}function o(e,t){switch(e.blend){case`Add`:return e.modelDefault+e.currentValue;case`Multiply`:return t.getParameterValueById(e.parameterId)*e.currentValue;default:return e.currentValue}}function s(e){for(let n of t.expressions.values())if(n.parameterId===e)return n}function c(){t.dispose()}function l(e){switch(e){case`Add`:return`Add`;case`Multiply`:return`Multiply`;default:return`Overwrite`}}function u(t){let n=e.internalModel.value;if(!n)return 0;try{let e=n.coreModel.getParameterDefaultValueById;if(typeof e==`function`){let r=e.call(n.coreModel,t);if(r!=null)return r}return n.coreModel.getParameterValueById(t)??0}catch{return 0}}return{initialise:r,applyExpressions:i,dispose:c}}var Er=[`x`,`y`,`scale`],Dr=y(!1),Or=y(`scale`),kr=D(`settings/live2d/position`,{x:0,y:0}),Ar=D(`settings/live2d/scale`,1),jr=e=>`${e.toFixed(1)}%`,Mr=e=>`${(e*100).toFixed(0)}%`,Q={x:{min:-500,max:500,step:.1,default:0,buttonText:`X`},y:{min:-500,max:500,step:.1,default:0,buttonText:`Y`},scale:{min:.01,max:3,step:.01,default:1,buttonText:`Scale`}},Nr={x:jr,y:jr,scale:Mr},Pr=(e,t,n)=>Math.min(Math.max(e,t),n);function Fr(){function e(e,t){let n=t===void 0?void 0:Pr(t,Q[e].min,Q[e].max);switch(e){case`x`:kr.value.x=n??Q.x.default;break;case`y`:kr.value.y=n??Q.y.default;break;case`scale`:Ar.value=n??Q.scale.default;break}}return{position:kr,scale:Ar,set:e,viewControlsEnabled:Dr,viewControlMode:Or}}var Ir={angleX:0,angleY:0,angleZ:0,leftEyeOpen:1,rightEyeOpen:1,leftEyeSmile:0,rightEyeSmile:0,leftEyebrowLR:0,rightEyebrowLR:0,leftEyebrowY:0,rightEyebrowY:0,leftEyebrowAngle:0,rightEyebrowAngle:0,leftEyebrowForm:0,rightEyebrowForm:0,mouthOpen:0,mouthForm:0,cheek:0,bodyAngleX:0,bodyAngleY:0,bodyAngleZ:0,breath:0},Lr=w(`live2d`,()=>{let{post:e,data:t}=ie({name:`airi-stores-stage-ui-live2d`}),n=y(new Set),r=e=>(n.value.add(e),()=>{n.value.delete(e)});function i(){e({type:`live2d-should-update-view`}),n.value.forEach(e=>e())}d(t,e=>{e?.type===`live2d-should-update-view`&&n.value.forEach(e=>e())});let a=j(`settings/live2d/current-motion`,()=>({group:`Idle`,index:0})),o=j(`settings/live2d/available-motions`,()=>[]),s=j(`settings/live2d/motion-map`,{}),{position:c,scale:l,set:u}=Fr(),f=j(`settings/live2d/parameters`,Ir);function p(){Er.forEach(e=>u(e)),a.reset(),o.reset(),s.reset(),f.reset(),i()}return{position:c,currentMotion:a,availableMotions:o,motionMap:s,scale:l,modelParameters:f,onShouldUpdateView:r,shouldUpdateView:i,resetState:p}}),Rr=j(`settings/live2d/eye-tracking`,!0),zr=j(`settings/live2d/model-eye-offset`,{x:0,y:0}),Br=j(`settings/live2d/idle-animation-enabled`,!0),Vr=j(`settings/live2d/idle-eye-animation-enabled`,!0),Hr=H(`settings/live2d/auto-blink-enabled`,!0,{defaultVersion:`2.0.0`,satisfiesVersionBy(e,t){return e===t}}),Ur=H(`settings/live2d/force-auto-blink-enabled`,!0,{defaultVersion:`2.0.0`,satisfiesVersionBy(e,t){return e===t}}),Wr=j(`settings/live2d/expression-enabled`,!1),Gr=j(`settings/live2d/shadow-enabled`,!0),Kr=j(`settings/live2d/max-fps`,0),qr=j(`settings/live2d/render-scale`,2);function Jr(){Rr.reset(),zr.reset(),Br.reset(),Vr.reset(),Hr.reset(),Ur.reset(),Wr.reset(),Gr.reset(),Kr.reset(),qr.reset()}var Yr=w(`settings-live2d`,()=>({live2dEyeTracking:Rr,live2dModelEyeOffset:zr,live2dIdleAnimationEnabled:Br,live2dForceIdleEyeAnimation:Vr,live2dAutoBlinkEnabled:Hr,live2dForceAutoBlinkEnabled:Ur,live2dExpressionEnabled:Wr,live2dShadowEnabled:Gr,live2dMaxFps:Kr,live2dRenderScale:qr,resetState:Jr}));function Xr(e){let{live2dRenderScale:t,live2dModelEyeOffset:n}=C(Yr()),{scale:r}=Fr();return b(()=>{let{normalizedScale:i,modelWidth:a,modelHeight:o}=h(e.model),s=t.value,c=h(e.source),l=h(e.canvas)?.getBoundingClientRect();if(!c||!l)return{x:1e3,y:1e3};let u={x:n.value.x/100*a*i*r.value,y:n.value.y/100*o*i*r.value};return{x:(c.x-l.left+u.x)*s,y:(c.y-l.top+u.y)*s}})}function Zr(e){let{internalModel:t,motionManager:n,modelParameters:r,live2dEyeTrackingEnabled:i,live2dEyeFocusSourceActive:a,live2dIdleAnimationEnabled:o,live2dForceIdleEyeAnimation:s,live2dAutoBlinkEnabled:c,live2dForceAutoBlinkEnabled:l,lastUpdateTime:u}=e,d=[],f=[],p=[];function m(e,t=`pre`){t===`pre`?d.push(e):t===`final`?p.push(e):f.push(e)}function h(e,t){for(let n of e){if(t.handled)break;n(t)}}function g(e,m,g){let _=u.value?m-u.value:0,v=localStorage.getItem(`selected-runtime-motion-group`),y={model:e,now:m,timeDelta:_,hookedUpdate:g,internalModel:t,motionManager:n,modelParameters:r,live2dEyeTrackingEnabled:i,live2dEyeFocusSourceActive:a,live2dIdleAnimationEnabled:o,live2dForceIdleEyeAnimation:s,live2dAutoBlinkEnabled:c,live2dForceAutoBlinkEnabled:l,isIdleMotion:!n.state.currentGroup||n.state.currentGroup===n.groups.idle||!!v&&n.state.currentGroup===v,handled:!1,markHandled:()=>{y.handled=!0}};h(d,y),!y.handled&&y.hookedUpdate&&y.hookedUpdate.call(n,e,m)&&(y.handled=!0),h(f,y);for(let e of p)e(y);return u.value=m,y.handled}return{register:m,hookUpdate:g}}function Qr(e){return t=>{e.updateTargets(t.now);let n=t.model.getParameterValueById(`ParamAngleX`),r=t.model.getParameterValueById(`ParamAngleY`),i=t.model.getParameterValueById(`ParamAngleZ`);{let r=e.targetX.value,i=n,a=e.velocityX.value,o=(120*(r-i)-16*a)/1;e.velocityX.value=a+o*t.timeDelta,n=i+e.velocityX.value*t.timeDelta,Math.abs(r-n)<.01&&Math.abs(e.velocityX.value)<.01&&(n=r,e.velocityX.value=0)}{let n=e.targetY.value,i=r,a=e.velocityY.value,o=(120*(n-i)-16*a)/1;e.velocityY.value=a+o*t.timeDelta,r=i+e.velocityY.value*t.timeDelta,Math.abs(n-r)<.01&&Math.abs(e.velocityY.value)<.01&&(r=n,e.velocityY.value=0)}{let n=e.targetZ.value,r=i,a=e.velocityZ.value,o=(120*(n-r)-16*a)/1;e.velocityZ.value=a+o*t.timeDelta,i=r+e.velocityZ.value*t.timeDelta,Math.abs(n-i)<.01&&Math.abs(e.velocityZ.value)<.01&&(i=n,e.velocityZ.value=0)}t.model.setParameterValueById(`ParamAngleX`,n),t.model.setParameterValueById(`ParamAngleY`,r),t.model.setParameterValueById(`ParamAngleZ`,i)}}function $r(e=vr()){return t=>{t.handled||!t.live2dIdleAnimationEnabled.value&&t.isIdleMotion&&(t.motionManager.stopAllMotions(),t.live2dForceIdleEyeAnimation.value&&(!t.live2dEyeTrackingEnabled.value||!t.live2dEyeFocusSourceActive.value)&&e.update(t.internalModel,t.now),t.internalModel.eyeBlink!=null&&t.internalModel.eyeBlink.updateParameters(t.model,t.timeDelta/1e3),t.model.setParameterValueById(`ParamEyeLOpen`,t.modelParameters.value.leftEyeOpen),t.model.setParameterValueById(`ParamEyeROpen`,t.modelParameters.value.rightEyeOpen),t.markHandled())}}function ei(e=vr()){return t=>{!t.isIdleMotion||t.handled||t.live2dForceIdleEyeAnimation.value&&(t.live2dEyeTrackingEnabled.value&&t.live2dEyeFocusSourceActive.value||e.update(t.internalModel,t.now))}}function ti(e){let t={phase:`idle`,progress:0,startLeft:1,startRight:1,delayMs:0,openDurationMs:300},n=1,r=1,i=3e3,a=e=>Math.min(1,Math.max(0,e)),o=()=>150+Math.random()*150;function s(){t.phase=`idle`,t.progress=0,t.delayMs=i+Math.random()*(8e3-i)}s();function c(e){return 1-(1-e)*(1-e)}function l(e){return e*e}function u(e,n,r){if(t.phase===`idle`)return t.delayMs=Math.max(0,t.delayMs-e),t.delayMs===0&&(t.phase=`closing`,t.progress=0,t.startLeft=n,t.startRight=r),{eyeLOpen:n,eyeROpen:r};if(t.phase===`closing`){t.progress=Math.min(1,t.progress+e/75);let n=c(t.progress),r=a(t.startLeft*(1-n)),i=a(t.startRight*(1-n));return t.progress>=1&&(t.phase=`opening`,t.progress=0,t.openDurationMs=o()),{eyeLOpen:r,eyeROpen:i}}t.progress=Math.min(1,t.progress+e/t.openDurationMs);let i=l(t.progress),u=a(t.startLeft*i),d=a(t.startRight*i);return t.progress>=1&&s(),{eyeLOpen:u,eyeROpen:d}}return i=>{if(!e?.value){if(!i.isIdleMotion||i.handled)return;let e=a(i.modelParameters.value.leftEyeOpen),t=a(i.modelParameters.value.rightEyeOpen);if(!i.live2dAutoBlinkEnabled.value){s(),i.model.setParameterValueById(`ParamEyeLOpen`,e),i.model.setParameterValueById(`ParamEyeROpen`,t),i.markHandled();return}if(i.live2dForceAutoBlinkEnabled.value||!i.internalModel.eyeBlink){let{eyeLOpen:n,eyeROpen:r}=u(i.timeDelta*1e3||16,e,t);i.model.setParameterValueById(`ParamEyeLOpen`,n),i.model.setParameterValueById(`ParamEyeROpen`,r),i.markHandled();return}i.internalModel.eyeBlink.updateParameters(i.model,i.timeDelta/1e3);let n=i.model.getParameterValueById(`ParamEyeLOpen`),r=i.model.getParameterValueById(`ParamEyeROpen`);i.model.setParameterValueById(`ParamEyeLOpen`,a(n*e)),i.model.setParameterValueById(`ParamEyeROpen`,a(r*t)),i.markHandled();return}if(!i.isIdleMotion)return;let o=a(i.modelParameters.value.leftEyeOpen),c=a(i.modelParameters.value.rightEyeOpen);if(!i.live2dAutoBlinkEnabled.value){s();let e=i.model.getParameterValueById(`ParamEyeLOpen`),t=i.model.getParameterValueById(`ParamEyeROpen`);i.model.setParameterValueById(`ParamEyeLOpen`,a(e*o)),i.model.setParameterValueById(`ParamEyeROpen`,a(t*c));return}if(!i.live2dForceAutoBlinkEnabled.value&&i.internalModel.eyeBlink!=null){s();let e=i.model.getParameterValueById(`ParamEyeLOpen`),t=i.model.getParameterValueById(`ParamEyeROpen`);i.model.setParameterValueById(`ParamEyeLOpen`,a(e*o)),i.model.setParameterValueById(`ParamEyeROpen`,a(t*c));return}let l=i.model.getParameterValueById(`ParamEyeLOpen`),d=i.model.getParameterValueById(`ParamEyeROpen`),f=.15;if(t.phase===`idle`&&l<=f&&d<=f){s();return}t.phase===`idle`&&(n=l,r=d);let p=t.phase!==`idle`,{eyeLOpen:m,eyeROpen:h}=u(i.timeDelta*1e3||16,1,1);if(p&&t.phase===`idle`){i.model.setParameterValueById(`ParamEyeLOpen`,a(n*o)),i.model.setParameterValueById(`ParamEyeROpen`,a(r*c));return}t.phase!==`idle`&&(i.model.setParameterValueById(`ParamEyeLOpen`,a(n*m*o)),i.model.setParameterValueById(`ParamEyeROpen`,a(r*h*c)))}}function ni(e){return t=>{e.applyExpressions(t.model)}}function ri(e,t){let n=0,r=0,i=0,a=e=>e*e*(3-2*e);return o=>{if(t.value){i=e.value,n=200,r=500,o.model.setParameterValueById(`ParamMouthOpenY`,e.value);return}if(n<=0){r>0&&(r=Math.max(0,r-o.timeDelta*1e3),o.model.setParameterValueById(`ParamMouthOpenY`,0));return}n=Math.max(0,n-o.timeDelta*1e3);let s=a(1-n/200),c=o.model.getParameterValueById(`ParamMouthOpenY`),l=i*(1-s)+c*s;o.model.setParameterValueById(`ParamMouthOpenY`,l)}}var ii=A(ne),ai=b(()=>T()&&ii.smallerOrEqual(`md`).value?.75:1);function oi(e,t){return b(()=>{let n=h(e),r=h(t),i=n.height/r.height*2,a=n.width/r.width*2,o=Math.min(i,a);return(Number.isNaN(o)||o<=0)&&(o=1e-6),{scale:o,x:n.width/2,y:n.height*ai.value}})}var $=function(e){return e.Happy=`happy`,e.Sad=`sad`,e.Angry=`angry`,e.Think=`think`,e.Surprise=`surprised`,e.Awkward=`awkward`,e.Question=`question`,e.Curious=`curious`,e.Neutral=`neutral`,e}({});Object.values($);var si=`Idle`;$.Happy,$.Sad,$.Angry,$.Think,$.Surprise,$.Awkward,$.Question,$.Neutral,$.Curious,$.Happy,$.Sad,$.Angry,$.Think,$.Surprise,$.Awkward,$.Question,$.Neutral,$.Curious;function ci(e,t){return!Number.isFinite(e)||!Number.isFinite(t)||e<=0||t<=0?`desktop`:t>=e?`portrait`:e<=900||t<=360?`compact-landscape`:`desktop`}function li(){return globalThis.document?.body?.dataset?.cloudView===`resident`&&ci(globalThis.innerWidth,globalThis.innerHeight)!==`desktop`}function ui(e,t){return Number.isFinite(e)&&Number.isFinite(t)&&e>0&&t>0&&e/t<=.4}function di(){return globalThis.document?.body?.dataset?.cloudView===`resident`&&ui(globalThis.innerWidth,globalThis.innerHeight)?2:1}function fi(e,t,n=1,r=void 0){let i=e.right-e.left,a=e.bottom-e.top;if(![i,a,t.width,t.height,n].every(e=>Number.isFinite(e)&&e>0))return;let o=Math.min(t.width/(i*.64),t.height*.88/(a*.6))*.94*n;return{scale:o,x:t.width/2-(Number.isFinite(r)?r:(e.left+e.right)/2)*o,y:t.height*.04-e.top*o}}var pi=new WeakMap,mi=new WeakSet;function hi(e){let t=e?.internalModel;if(t?.settings?.json?.Neighbour?.fit!==`visible-contain-v1`||mi.has(e))return;let n=t.coreModel,r=Array.from(n.getModel().parameters.ids);if(!r.includes(`ParamMouthOpenY`)&&r.includes(`PARAM_MOUTH_OPEN_Y`)){let e=n.getParameterIndex;n.getParameterIndex=function(t){return e.call(this,t===`ParamMouthOpenY`?`PARAM_MOUTH_OPEN_Y`:t)}}mi.add(e)}function gi(e,t,n,r){let i=e?.internalModel,a=li(),o=typeof r==`string`&&/^(?:cloud-live2d-|display-model-sha256-live2d-zip-)8b93e71f792d13de4588c99b7c469e82f3f0e6cc9389257780812b5dafaa5c31$/.test(r);if(!i||!a&&i.settings?.json?.Neighbour?.fit!==`visible-contain-v1`&&!o)return n;let s=pi.get(e);if(!s){let t=i.coreModel,r=1/0,a=1/0,o=-1/0,c=-1/0,l=[];for(let e=0;e<t.getDrawableCount();e++){if(t.getDrawableOpacity(e)<=.01)continue;let n=i.getDrawableVertices(e);for(let e=0;e+1<n.length;e+=2){let t=i.localTransform.apply({x:n[e],y:n[e+1]});!Number.isFinite(t.x)||!Number.isFinite(t.y)||(l.push([t.x,t.y]),r=Math.min(r,t.x),o=Math.max(o,t.x),a=Math.min(a,t.y),c=Math.max(c,t.y))}}if(o<=r||c<=a)return n;let u=l.filter(e=>e[1]<=a+(c-a)*.35).map(e=>e[0]).sort((e,t)=>e-t),d=Math.floor(u.length/2),f=u.length?(u[d]+u[Math.max(0,d-+(u.length%2==0))])/2:(r+o)/2;s={left:r,right:o,top:a,bottom:c,focusX:f},pi.set(e,s)}if(a){let e=di(),r=fi(s,t,e,e>1?s.focusX:void 0);return r?{scale:r.scale,x:r.x+i.width/2*r.scale,y:r.y+i.height/2*r.scale}:n}let c=Math.min(t.width/(s.right-s.left),t.height/(s.bottom-s.top))*.9;return!Number.isFinite(c)||c<=0?n:{scale:c,x:t.width/2-(s.left+s.right-i.width)/2*c,y:t.height/2-(s.top+s.bottom-i.height)/2*c}}var _i=m({__name:`Model`,props:x({modelSrc:{},modelId:{},app:{},mouthOpenSize:{default:0},nowSpeaking:{type:Boolean,default:!1},width:{},height:{},paused:{type:Boolean,default:!1},focusAt:{default:()=>({x:0,y:0})},eyeTracking:{type:Boolean,default:!1},eyeFocusSourceActive:{type:Boolean,default:!1},themeColorsHue:{default:220.44},themeColorsHueDynamic:{type:Boolean,default:!1},live2dIdleAnimationEnabled:{type:Boolean,default:!0},live2dForceIdleEyeAnimation:{type:Boolean,default:!0},live2dAutoBlinkEnabled:{type:Boolean,default:!0},live2dForceAutoBlinkEnabled:{type:Boolean,default:!1},live2dExpressionEnabled:{type:Boolean,default:!0},live2dShadowEnabled:{type:Boolean,default:!0}},{state:{default:`pending`},stateModifiers:{}}),emits:x([`modelLoaded`,`error`],[`update:state`]),setup(e,{expose:n,emit:o}){let f=e,m=o,h=u(e,`state`),{position:g,scale:v}=Fr(),x=_(()=>f.modelSrc),S=y(!1),w=!1,T=new ae,ee=b(()=>({x:g.value.x/100*f.width,y:-(g.value.y/100)*f.height})),D=_(()=>f.app),O=_(()=>f.paused),k=_(()=>f.focusAt),A=y(),ne=y(0),re=y(0),ie=b(()=>Math.max(0,Math.min(100,f.mouthOpenSize))),j=_(()=>f.nowSpeaking),M=y(0),{isDark:ce}=E(),N=r(new Ft({alpha:.2,blur:0,distance:20,rotation:45})),P,le=oi(()=>({width:f.width,height:f.height}),()=>({width:ne.value,height:re.value}));d([ee,v,le],()=>{ue()});function ue(e=!1){if(!A.value)return;let t=gi(A.value,{width:f.width,height:f.height},le.value,f.modelId),n=li()?1:v.value,r=li()?{x:0,y:0}:ee.value;if(!e){A.value.scale.set(t.scale*n,t.scale*n),A.value.x=t.x+r.x,A.value.y=t.y+r.y;return}P?.pause();let i={scale:A.value.scale.x,x:A.value.x,y:A.value.y};P=pe(i,{scale:t.scale*n,x:t.x+r.x,y:t.y+r.y,duration:200,ease:`outQuad`,onUpdate:()=>{A.value&&(A.value.scale.set(i.scale,i.scale),A.value.x=i.x,A.value.y=i.y)}})}let F=Lr(),{currentMotion:de,availableMotions:I,motionMap:fe,modelParameters:L}=C(F),R=_(()=>f.themeColorsHue),z=_(()=>f.themeColorsHueDynamic),B=_(()=>f.live2dIdleAnimationEnabled),V=_(()=>f.eyeTracking),me=_(()=>f.eyeFocusSourceActive),ve=_(()=>f.live2dForceIdleEyeAnimation),ye=_(()=>f.live2dAutoBlinkEnabled),be=_(()=>f.live2dForceAutoBlinkEnabled),H=_(()=>f.live2dExpressionEnabled),U=_(()=>f.live2dShadowEnabled),W=y(),G=Tr({internalModel:W,modelId:f.modelId}),xe=r(null),Se=r(null),Ce=y({group:`Idle`,index:0}),we=br({baseAngles:()=>({x:L.value.angleX,y:L.value.angleY,z:L.value.angleZ}),initialStyle:`sway-sine`}),Te=F.onShouldUpdateView(()=>{Ee()});async function Ee(){if(await te(S).not.toBeTruthy(),await T.acquire(),S.value=!0,h.value=`loading`,window.dispatchEvent(new CustomEvent(`resident-render-state`,{detail:{state:`pending`,modelId:f.modelId}})),!D.value||!D.value.stage)try{await te(()=>!!D.value&&!!D.value.stage).toBeTruthy({timeout:1500})}catch{S.value=!1,h.value=`mounted`,T.release();return}if(A.value&&D.value?.stage){G.dispose(),W.value=void 0;try{D.value.stage.removeChild(A.value),A.value.destroy()}catch(e){console.warn(`Error removing old model:`,e)}A.value=void 0}if(!x.value){console.warn(`No Live2D model source provided.`),S.value=!1,h.value=`mounted`,T.release();return}let e=f.modelId,t=x.value;try{if(w){S.value=!1,h.value=`mounted`;return}let n=new ge;if(await _e.setupLive2DModel(n,{url:t,id:e},{autoInteract:!1}),w||!D.value?.stage||e!==f.modelId||t!==x.value){n.destroy();return}hi(n),I.value.forEach(e=>{e.motionName in $?fe.value[e.fileName]=e.motionName:fe.value[e.fileName]=si}),A.value=n,D.value.stage.addChild(A.value),ne.value=A.value.width,re.value=A.value.height,A.value.anchor.set(.5,.5),ue(),A.value.on(`hit`,e=>{A.value&&e.includes(`body`)&&A.value.motion(`tap_body`)});let r=A.value.internalModel,i=r.coreModel,a=r.motionManager;i.setParameterValueById(`ParamMouthOpenY`,ie.value),I.value=Object.entries(a.definitions).flatMap(([e,t])=>t?.map((t,n)=>({motionName:e,motionIndex:n,fileName:t.File}))||[]).filter(Boolean);let o=localStorage.getItem(`selected-runtime-motion-group`),s=localStorage.getItem(`selected-runtime-motion-index`);if(o!==null&&s){let e=a.groups[o];if(e!==void 0&&a.motionGroups[e]){let t=Number.parseInt(s),n=a.motionGroups[e][t];n&&n._looper&&(n._looper.loopDuration=0,console.info(`Configured motion to loop infinitely:`,o,t))}}o!==null&&s&&B.value&&setTimeout(()=>{console.info(`Playing selected runtime motion:`,o,s),de.value={group:o,index:Number.parseInt(s)}},300),a.groups.idle&&a.motionGroups[a.groups.idle]?.forEach(e=>{e._motionData.curves.forEach(e=>{(e.id===`ParamEyeBallX`||e.id===`ParamEyeBallY`)&&(e.id=`_${e.id}`)})});let c=Zr({internalModel:r,motionManager:a,modelParameters:L,live2dEyeTrackingEnabled:V,live2dEyeFocusSourceActive:me,live2dIdleAnimationEnabled:B,live2dForceIdleEyeAnimation:ve,live2dAutoBlinkEnabled:ye,live2dForceAutoBlinkEnabled:be,lastUpdateTime:M});c.register(Qr(we),`pre`),c.register($r(),`pre`),c.register(ei(),`post`),c.register(ni(G),`final`),c.register(ti(H),`final`),c.register(ri(ie,j),`final`),c.register(hr(),`final`);let l=a.update;a.update=function(e,t){return c.hookUpdate(e,t,l)},a.on(`motionStart`,(e,t)=>{Ce.value={group:e,index:t}}),a.on(`motionFinish`,()=>{let e=localStorage.getItem(`selected-runtime-motion-group`),t=localStorage.getItem(`selected-runtime-motion-index`);e!==null&&t&&B.value&&(console.info(`Motion finished, restarting runtime motion:`,e,t),requestAnimationFrame(()=>{de.value={group:e,index:Number.parseInt(t)}}))}),i.setParameterValueById(`ParamAngleX`,L.value.angleX),i.setParameterValueById(`ParamAngleY`,L.value.angleY),i.setParameterValueById(`ParamAngleZ`,L.value.angleZ),i.setParameterValueById(`ParamEyeLOpen`,L.value.leftEyeOpen),i.setParameterValueById(`ParamEyeROpen`,L.value.rightEyeOpen),i.setParameterValueById(`ParamEyeSmile`,L.value.leftEyeSmile),i.setParameterValueById(`ParamBrowLX`,L.value.leftEyebrowLR),i.setParameterValueById(`ParamBrowRX`,L.value.rightEyebrowLR),i.setParameterValueById(`ParamBrowLY`,L.value.leftEyebrowY),i.setParameterValueById(`ParamBrowRY`,L.value.rightEyebrowY),i.setParameterValueById(`ParamBrowLAngle`,L.value.leftEyebrowAngle),i.setParameterValueById(`ParamBrowRAngle`,L.value.rightEyebrowAngle),i.setParameterValueById(`ParamBrowLForm`,L.value.leftEyebrowForm),i.setParameterValueById(`ParamBrowRForm`,L.value.rightEyebrowForm),i.setParameterValueById(`ParamMouthOpenY`,L.value.mouthOpen),i.setParameterValueById(`ParamMouthForm`,L.value.mouthForm),i.setParameterValueById(`ParamCheek`,L.value.cheek),i.setParameterValueById(`ParamBodyAngleX`,L.value.bodyAngleX),i.setParameterValueById(`ParamBodyAngleY`,L.value.bodyAngleY),i.setParameterValueById(`ParamBodyAngleZ`,L.value.bodyAngleZ),i.setParameterValueById(`ParamBreath`,L.value.breath),xe.value=r.eyeBlink,Se.value=a.expressionManager,H.value&&(a.expressionManager&&=null,r.eyeBlink&&=null,W.value=r),m(`modelLoaded`),window.dispatchEvent(new CustomEvent(`resident-render-state`,{detail:{state:`ready`,modelId:e}}))}catch(n){e===f.modelId&&t===x.value&&window.dispatchEvent(new CustomEvent(`resident-render-state`,{detail:{state:`failed`,modelId:e}})),console.error(`[Live2D] Failed to load model:`,n),m(`error`,n instanceof Error?n:Error(String(n)))}finally{S.value=!1,h.value=`mounted`,await De(W.value).catch(e=>{console.warn(`[Model.vue] Expression controller initialization failed:`,e)}),T.release()}}async function De(e){G.dispose();let t=e?.settings;if(!t)return;let n=t.expressions??[];n.length!==0&&await G.initialise(n,async e=>{let n=t.resolveURL?.(e)??e,r=await fetch(n);if(!r.ok)throw Error(`Failed to fetch exp3 file: ${e} (${r.status})`);return r.text()})}async function K(e,t){if(!A.value){console.warn(`Cannot set motion: model not loaded`);return}console.info(`Setting motion:`,e,`index:`,t);try{await A.value.motion(e,t,he.FORCE),console.info(`Motion started successfully:`,e)}catch(t){console.error(`Failed to start motion:`,e,t)}}let q=y(),J=y(0);function Y(){if(!A.value)return;if(!U.value){A.value.filters=[];return}if(!q.value)return;let e=getComputedStyle(q.value).backgroundColor;N.value.color=Number(oe(e).replace(`#`,`0x`)),A.value.filters=[N.value]}d(x,async()=>await Ee(),{immediate:!0}),d(ce,Y,{immediate:!0}),d([A,R],Y),d(U,Y);function Oe(){if(Y(),!U.value){J.value=0;return}J.value=requestAnimationFrame(Oe)}d([z,U],([e,t])=>{e&&t?J.value=requestAnimationFrame(Oe):(cancelAnimationFrame(J.value),J.value=0)},{immediate:!0}),d(de,e=>K(e.group,e.index)),d(O,e=>e?D.value?.stop():D.value?.start()),d(()=>L.value.angleX,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamAngleX`,e)}),d(()=>L.value.angleY,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamAngleY`,e)}),d(()=>L.value.angleZ,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamAngleZ`,e)}),d(()=>L.value.leftEyeOpen,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamEyeLOpen`,e)}),d(()=>L.value.rightEyeOpen,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamEyeROpen`,e)}),d(()=>L.value.mouthOpen,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamMouthOpenY`,e)}),d(()=>L.value.mouthForm,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamMouthForm`,e)}),d(()=>L.value.cheek,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamCheek`,e)}),d(()=>L.value.bodyAngleX,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBodyAngleX`,e)}),d(()=>L.value.bodyAngleY,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBodyAngleY`,e)}),d(()=>L.value.bodyAngleZ,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBodyAngleZ`,e)}),d(()=>L.value.breath,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBreath`,e)}),d(()=>L.value.leftEyebrowLR,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowLX`,e)}),d(()=>L.value.rightEyebrowLR,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowRX`,e)}),d(()=>L.value.leftEyebrowY,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowLY`,e)}),d(()=>L.value.rightEyebrowY,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowRY`,e)}),d(()=>L.value.leftEyebrowAngle,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowLAngle`,e)}),d(()=>L.value.rightEyebrowAngle,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowRAngle`,e)}),d(()=>L.value.leftEyebrowForm,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowLForm`,e)}),d(()=>L.value.rightEyebrowForm,e=>{A.value&&A.value.internalModel.coreModel.setParameterValueById(`ParamBrowRForm`,e)}),d(B,e=>{if(!e&&A.value){let e=A.value.internalModel;e?.motionManager&&e.motionManager.stopAllMotions()}}),d(H,e=>{if(!A.value)return;let t=A.value.internalModel,n=t.motionManager;e?(n.expressionManager&&=null,t.eyeBlink&&=null,W.value=t,De(t).catch(e=>{console.warn(`[Model.vue] Expression controller initialisation failed:`,e)})):(n.expressionManager=Se.value,t.eyeBlink=xe.value,G.dispose(),W.value=void 0)}),d(k,e=>{A.value&&f.eyeTracking&&A.value.focus(e.x,e.y)}),a(()=>{let e=se(()=>we.scheduleBeat());i(()=>e())}),a(async()=>{Y()}),i(()=>{w=!0,P?.pause(),Te?.(),G.dispose()});function ke(){return I.value}return n({setMotion:K,listMotionGroups:ke,modelNormalizeParams:le,initialModelHeight:re,initialModelWidth:ne}),(void 0)?.dispose(()=>{console.warn(`[Dev] Reload on HMR dispose is active for this component. Performing a full reload.`),window.location.reload()}),(e,n)=>(l(),c(p,null,[s(`div`,{ref_key:`dropShadowColorComputer`,ref:q,hidden:``,bg:`primary-400 dark:primary-500`},null,512),t(e.$slots,`default`)],64))}}),vi=m({__name:`Live2D`,props:x({cursorPosition:{},modelSrc:{},modelId:{},paused:{type:Boolean,default:!1},mouthOpenSize:{default:0},nowSpeaking:{type:Boolean,default:!1},themeColorsHue:{default:220.44},themeColorsHueDynamic:{type:Boolean,default:!1}},{state:{default:`pending`},stateModifiers:{},canvasState:{default:`pending`},canvasStateModifiers:{},modelState:{default:`pending`},modelStateModifiers:{}}),emits:[`update:state`,`update:canvasState`,`update:modelState`],setup(e,{expose:t}){let r=e,a=u(e,`state`),s=u(e,`canvasState`),c=u(e,`modelState`),p=y(),m=y(),h=y(null),_,{live2dEyeTracking:v,live2dIdleAnimationEnabled:b,live2dForceIdleEyeAnimation:x,live2dAutoBlinkEnabled:S,live2dForceAutoBlinkEnabled:w,live2dExpressionEnabled:T,live2dMaxFps:E,live2dRenderScale:D,live2dShadowEnabled:O}=C(Yr()),te=Xr({canvas:()=>p.value?.canvasElement(),model:()=>({normalizedScale:m.value?.modelNormalizeParams.scale??1,modelWidth:m.value?.initialModelWidth??1e3,modelHeight:m.value?.initialModelHeight??1e3}),source:h});return d(()=>r.cursorPosition,e=>{h.value=e?{...e}:null,_&&clearTimeout(_),_=setTimeout(()=>{h.value=null},1e3)}),i(()=>{_&&clearTimeout(_)}),d([c,s],()=>{a.value=c.value===`mounted`&&s.value===`mounted`?`mounted`:`loading`}),t({canvasElement:()=>p.value?.canvasElement(),captureFrame:()=>p.value?.captureFrame()}),(t,r)=>(l(),n(o(ee),{relative:``},{default:f(({width:t,height:n})=>[g(U,{ref_key:`live2dCanvasRef`,ref:p,state:s.value,"onUpdate:state":r[1]||=e=>s.value=e,width:t,height:n,resolution:o(D),"max-fps":o(E),"max-h":`100dvh`},{default:f(({app:i})=>[g(_i,{ref_key:`live2dModelRef`,ref:m,state:c.value,"onUpdate:state":r[0]||=e=>c.value=e,"model-src":e.modelSrc,"model-id":e.modelId,app:i,"mouth-open-size":e.mouthOpenSize,"now-speaking":e.nowSpeaking,width:t,height:n,paused:e.paused,"focus-at":o(te),"eye-tracking":o(v),"eye-focus-source-active":!!h.value,"theme-colors-hue":e.themeColorsHue,"theme-colors-hue-dynamic":e.themeColorsHueDynamic,"live2d-idle-animation-enabled":o(b),"live2d-force-idle-eye-animation":o(x),"live2d-auto-blink-enabled":o(S),"live2d-force-auto-blink-enabled":o(w),"live2d-expression-enabled":o(T),"live2d-shadow-enabled":o(O)},null,8,[`state`,`model-src`,`model-id`,`app`,`mouth-open-size`,`now-speaking`,`width`,`height`,`paused`,`focus-at`,`eye-tracking`,`eye-focus-source-active`,`theme-colors-hue`,`theme-colors-hue-dynamic`,`live2d-idle-animation-enabled`,`live2d-force-idle-eye-animation`,`live2d-auto-blink-enabled`,`live2d-force-auto-blink-enabled`,`live2d-expression-enabled`,`live2d-shadow-enabled`])]),_:2},1032,[`state`,`width`,`height`,`resolution`,`max-fps`])]),_:1}))}});export{Lr as a,Er as c,br as d,_r as f,Ir as i,Fr as l,_i as n,Q as o,U as p,Yr as r,Nr as s,vi as t,wr as u};
//# sourceMappingURL=src-Dr8tDJwq.js.map