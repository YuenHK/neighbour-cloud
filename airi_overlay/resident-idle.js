// Wall-clock expiry also handles a throttled or sleeping browser tab.
export class ResidentIdle {
  deadline = 0
  timer = undefined
  constructor(expire, {
    now = () => Date.now(),
    setTimer = (callback, delay) => globalThis.setTimeout(callback, delay),
    clearTimer = timer => globalThis.clearTimeout(timer),
  } = {}) {
    this.expire = expire
    this.now = now
    this.setTimer = setTimer
    this.clearTimer = clearTimer
  }

  touch() {
    this.deadline = this.now() + 180000
    this.arm()
  }

  arm() {
    this.clearTimer(this.timer)
    this.timer = this.setTimer(() => this.check(), Math.max(0, this.deadline - this.now()))
  }

  check() {
    if (!this.deadline)
      return
    if (this.now() < this.deadline) {
      this.arm()
      return
    }
    this.stop()
    this.expire()
  }

  stop() {
    this.clearTimer(this.timer)
    this.timer = undefined
    this.deadline = 0
  }
}
