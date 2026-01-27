export class RingBuffer<T> {
  private buf: (T | undefined)[];
  private idx = 0;
  private count = 0;

  constructor(private readonly size: number) {
    this.buf = new Array<T | undefined>(size);
  }

  push(item: T): void {
    this.buf[this.idx] = item;
    this.idx = (this.idx + 1) % this.size;
    if (this.count < this.size) {
      this.count += 1;
    }
  }

  values(): T[] {
    if (this.count === 0) return [];
    const start = this.count === this.size ? this.idx : 0;
    const result: T[] = [];
    for (let i = 0; i < this.count; i++) {
      const v = this.buf[(start + i) % this.size];
      if (v !== undefined) {
        result.push(v);
      }
    }
    return result;
  }

  length(): number {
    return this.count;
  }
}
