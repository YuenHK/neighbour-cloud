//#region src/analyser.protocol.ts
const ANALYSER_WORKLET_PROCESSOR_NAME = "workletAnalyserProcessor";
const DEFAULT_ANALYSER_WORKLET_PARAMS = {
	minBeatInterval: .2,
	sensitivity: .7,
	lowpassFilterFrequency: 200,
	highpassFilterFrequency: 30,
	envelopeFilterFrequency: 12,
	warmup: true,
	bufferDuration: 4,
	adaptiveThreshold: true,
	spectralFlux: true
};

//#endregion
//#region src/biquad-filter.ts
function createBiquadFilter(type, cutOff, sampleRate$1, q = 1 / Math.SQRT2) {
	const w0 = 2 * Math.PI * cutOff / sampleRate$1;
	const cosW0 = Math.cos(w0);
	const alpha = Math.sin(w0) / (2 * q);
	const a0 = 1 + alpha;
	const a1 = -2 * cosW0 / a0;
	const a2 = (1 - alpha) / a0;
	let b0, b1, b2;
	switch (type) {
		case "lowpass":
			b0 = (1 - cosW0) / 2 / a0;
			b1 = (1 - cosW0) / a0;
			b2 = (1 - cosW0) / 2 / a0;
			break;
		case "highpass":
			b0 = (1 + cosW0) / 2 / a0;
			b1 = -(1 + cosW0) / a0;
			b2 = (1 + cosW0) / 2 / a0;
			break;
		case "bandpass":
			b0 = alpha / a0;
			b1 = 0;
			b2 = -alpha / a0;
			break;
		default: throw new Error(`Unsupported filter type: ${type}`);
	}
	let x1 = 0;
	let x2 = 0;
	let y1 = 0;
	let y2 = 0;
	return {
		reset: () => {
			x1 = x2 = y1 = y2 = 0;
		},
		process: (sample) => {
			const y = b0 * sample + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
			x2 = x1;
			x1 = sample;
			y2 = y1;
			y1 = y;
			return y;
		}
	};
}

//#endregion
//#region src/envelope-filter.ts
function createEnvelopeFilter(cutOff, sampleRate$1) {
	const alpha = 1 / (1 + 1 / (2 * Math.PI * cutOff) * sampleRate$1);
	let y = 0;
	return {
		reset: () => {
			y = 0;
		},
		process: (x) => {
			y += alpha * (x - y);
			return y;
		}
	};
}

//#endregion
//#region src/analyser.worklet.ts
/**
* [Purposed] Not available today (as of August 2025)
*
* @see https://webaudio.github.io/web-audio-api/#dom-audioworkletglobalscope-renderquantumsize
*/
const renderQuantumSize = 128;
const EPSILON = 1e-6;
function checkDuration(duration) {
	return typeof duration === "number" && duration > EPSILON && Number.isFinite(duration);
}
function bufferCapacityFromDuration(duration) {
	return Math.ceil(duration * sampleRate / renderQuantumSize);
}
var AnalyserWorkletProcessor = class extends AudioWorkletProcessor {
	historyMeanBuffer;
	varianceBuffer;
	spectralFluxBuffer;
	lowpassFilter;
	highpassFilter;
	envelopeFilter;
	bufferCapacity;
	historyIndex = 0;
	isWarmedUp = false;
	lastBeatTime = -1;
	lastMeanEnergy = 0;
	isStopped = false;
	optMeanSum = 0;
	optMeanSquaresSum = 0;
	optVarianceSum = 0;
	params;
	constructor() {
		super();
		this.params = { ...DEFAULT_ANALYSER_WORKLET_PARAMS };
		this.bufferCapacity = bufferCapacityFromDuration(this.params.bufferDuration);
		this.historyMeanBuffer = new Float32Array(this.bufferCapacity);
		this.varianceBuffer = new Float32Array(this.bufferCapacity);
		this.spectralFluxBuffer = new Float32Array(this.bufferCapacity);
		this.envelopeFilter = createEnvelopeFilter(this.params.envelopeFilterFrequency, sampleRate);
		this.lowpassFilter = createBiquadFilter("lowpass", this.params.lowpassFilterFrequency, sampleRate);
		this.highpassFilter = createBiquadFilter("highpass", this.params.highpassFilterFrequency, sampleRate);
		this.port.onmessage = (event) => {
			switch (event.data.type) {
				case "parameters": {
					if (this.isStopped) return;
					const nextParams = event.data.parameters;
					let reset = event.data.reset;
					if (nextParams.lowpassFilterFrequency !== void 0 && nextParams.lowpassFilterFrequency !== this.params.lowpassFilterFrequency) {
						this.lowpassFilter = createBiquadFilter("lowpass", nextParams.lowpassFilterFrequency, sampleRate);
						reset = true;
					}
					if (nextParams.highpassFilterFrequency !== void 0 && nextParams.highpassFilterFrequency !== this.params.highpassFilterFrequency) {
						this.highpassFilter = createBiquadFilter("highpass", nextParams.highpassFilterFrequency, sampleRate);
						reset = true;
					}
					if (nextParams.envelopeFilterFrequency !== void 0 && nextParams.envelopeFilterFrequency !== this.params.envelopeFilterFrequency) {
						this.envelopeFilter = createEnvelopeFilter(nextParams.envelopeFilterFrequency, sampleRate);
						reset = true;
					}
					if (nextParams.bufferDuration !== void 0 && nextParams.bufferDuration !== this.params.bufferDuration) if (!checkDuration(nextParams.bufferDuration)) console.warn("Ignoring the invalid bufferDuration value");
					else {
						this.bufferCapacity = bufferCapacityFromDuration(nextParams.bufferDuration);
						reset = true;
					}
					if (reset) {
						this.historyMeanBuffer = new Float32Array(this.bufferCapacity);
						this.varianceBuffer = new Float32Array(this.bufferCapacity);
						this.spectralFluxBuffer = new Float32Array(this.bufferCapacity);
						this.historyIndex = 0;
						this.isWarmedUp = false;
						this.lastBeatTime = -1;
						this.lastMeanEnergy = 0;
						this.optMeanSum = 0;
						this.optMeanSquaresSum = 0;
						this.optVarianceSum = 0;
					}
					Object.assign(this.params, nextParams);
					break;
				}
				case "stop":
					this.isStopped = true;
					break;
			}
		};
	}
	process(inputs, outputs) {
		if (inputs.length < 1) {
			console.warn("Expected at least one input channel");
			return false;
		}
		const input = inputs[0];
		const output = outputs[0];
		const inputChannel = input?.[0];
		const outputChannel = output?.[0];
		if (!outputChannel) return false;
		if (!inputChannel) return !this.isStopped;
		let meanEnergy = 0;
		inputChannel.forEach((sample, i) => {
			let output$1 = this.highpassFilter.process(sample);
			output$1 = this.lowpassFilter.process(output$1);
			output$1 = this.envelopeFilter.process(output$1 ** 2);
			meanEnergy += output$1;
			outputChannel[i] = output$1;
		});
		meanEnergy /= inputChannel.length;
		const noiseGateThreshold = .01 * (1 - this.params.sensitivity * .9);
		if (meanEnergy < noiseGateThreshold) return !this.isStopped;
		const bufferIndex = this.historyIndex % this.historyMeanBuffer.length;
		{
			const staleMeanEnergy = this.historyMeanBuffer[bufferIndex] ?? 0;
			this.optMeanSum += meanEnergy - staleMeanEnergy;
			this.optMeanSquaresSum += meanEnergy ** 2 - staleMeanEnergy ** 2;
			this.historyMeanBuffer[bufferIndex] = meanEnergy;
		}
		const prevHistMeanEnergy = this.optMeanSum / this.historyMeanBuffer.length;
		const histMeanEnergy = prevHistMeanEnergy;
		if (this.params.adaptiveThreshold) {
			const meanSquares = this.optMeanSquaresSum / this.historyMeanBuffer.length;
			const variance = Math.max(0, meanSquares - prevHistMeanEnergy ** 2);
			const staleVariance = this.varianceBuffer[bufferIndex] ?? 0;
			this.varianceBuffer[bufferIndex] = variance;
			this.optVarianceSum += variance - staleVariance;
		}
		let spectralFlux = 0;
		if (this.params.spectralFlux && this.historyIndex > 0) {
			const rawFlux = meanEnergy - this.lastMeanEnergy;
			spectralFlux = Math.max(0, rawFlux);
			if (spectralFlux > 1e-8) spectralFlux = Math.log10(spectralFlux * 1e6 + 1) * Math.sqrt(meanEnergy);
			this.spectralFluxBuffer[bufferIndex] = spectralFlux;
		}
		this.lastMeanEnergy = meanEnergy;
		this.historyIndex++;
		if (this.historyIndex >= Number.MAX_SAFE_INTEGER - 1e3) this.historyIndex = this.historyMeanBuffer.length + this.historyIndex % this.historyMeanBuffer.length;
		if (this.historyIndex >= this.historyMeanBuffer.length) this.isWarmedUp = true;
		if (!this.isWarmedUp && this.params.warmup) return !this.isStopped;
		let threshold = histMeanEnergy * (3 - this.params.sensitivity * 1.8);
		if (this.params.adaptiveThreshold && histMeanEnergy > 1e-6) {
			const meanVariance = this.optVarianceSum / this.varianceBuffer.length;
			const adaptiveStrength = .5 + this.params.sensitivity * .5;
			const adaptiveFactor = .7 + Math.sqrt(meanVariance) / histMeanEnergy * adaptiveStrength;
			threshold *= adaptiveFactor;
		}
		const now = currentTime;
		const timeSinceLastBeat = now - this.lastBeatTime;
		let isBeat = false;
		if (this.params.spectralFlux) {
			const recentFluxHistory = Math.min(20, this.spectralFluxBuffer.length);
			let recentFluxMean = 0;
			let recentFluxVariance = 0;
			for (let i = 0; i < recentFluxHistory; i++) {
				const idx = (this.historyIndex - 1 - i + this.spectralFluxBuffer.length) % this.spectralFluxBuffer.length;
				const flux = this.spectralFluxBuffer[idx] ?? 0;
				recentFluxMean += flux;
			}
			recentFluxMean /= recentFluxHistory;
			for (let i = 0; i < recentFluxHistory; i++) {
				const idx = (this.historyIndex - 1 - i + this.spectralFluxBuffer.length) % this.spectralFluxBuffer.length;
				const flux = this.spectralFluxBuffer[idx] ?? 0;
				recentFluxVariance += (flux - recentFluxMean) ** 2;
			}
			recentFluxVariance /= recentFluxHistory;
			const fluxMultiplier = 3 - this.params.sensitivity * 1.5;
			const fluxThreshold = recentFluxMean + Math.sqrt(recentFluxVariance) * fluxMultiplier;
			const energyIncrease = meanEnergy / Math.max(histMeanEnergy, 1e-8);
			const energyThreshold = 1.1 + (1 - this.params.sensitivity) * .4;
			isBeat = spectralFlux > fluxThreshold && energyIncrease > energyThreshold && timeSinceLastBeat > this.params.minBeatInterval;
		} else isBeat = meanEnergy > threshold && timeSinceLastBeat > this.params.minBeatInterval;
		if (isBeat) {
			const recentHistory = Math.min(10, this.historyMeanBuffer.length);
			let recentMeanEnergy = 0;
			for (let i = 0; i < recentHistory; i++) {
				const idx = (this.historyIndex - 1 - i + this.historyMeanBuffer.length) % this.historyMeanBuffer.length;
				recentMeanEnergy += this.historyMeanBuffer[idx] ?? 0;
			}
			recentMeanEnergy /= recentHistory;
			const recentThresholdMultiplier = 1.1 + (1 - this.params.sensitivity) * .3;
			if (meanEnergy < recentMeanEnergy * recentThresholdMultiplier) isBeat = false;
		}
		if (isBeat) {
			this.lastBeatTime = now;
			this.port.postMessage({
				type: "beat",
				energy: meanEnergy,
				interval: timeSinceLastBeat
			});
		}
		return !this.isStopped;
	}
};
registerProcessor(ANALYSER_WORKLET_PROCESSOR_NAME, AnalyserWorkletProcessor);

//#endregion
export {  };