import { describe, expect, it } from "vitest";
import { encodeWav, mixToMono } from "./wav";

// jsdom'un Blob'unda arrayBuffer() yok; FileReader ile oku.
const readBuffer = (blob: Blob) =>
  new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });

describe("wav", () => {
  it("geçerli 16-bit mono WAV başlığı yazar", async () => {
    const blob = encodeWav(new Float32Array([0, 1, -1, 0.5]), 16000);
    const view = new DataView(await readBuffer(blob));
    const tag = (o: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(o + i)));
    expect([tag(0), tag(8), tag(36)]).toEqual(["RIFF", "WAVE", "data"]);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(40, true)).toBe(8);
    expect(view.getInt16(46, true)).toBe(32767);
    expect(view.getInt16(48, true)).toBe(-32768);
  });

  it("stereoyu ortalayarak mono yapar", () => {
    expect(Array.from(mixToMono([new Float32Array([1, 0]), new Float32Array([0, 1])]))).toEqual([0.5, 0.5]);
  });

  it("stereo yazar: sol/sağ kanal sırayla dizilir ve başlık 2 kanal der", async () => {
    const blob = encodeWav([new Float32Array([1, 0]), new Float32Array([0, -1])], 16000);
    const view = new DataView(await readBuffer(blob));
    expect(view.getUint16(22, true)).toBe(2);           // kanal sayısı
    expect(view.getUint16(32, true)).toBe(4);           // blok hizası
    expect(view.getUint32(40, true)).toBe(8);           // 2 kare x 2 kanal x 2 bayt
    expect([view.getInt16(44, true), view.getInt16(46, true), view.getInt16(48, true), view.getInt16(50, true)])
      .toEqual([32767, 0, 0, -32768]);
  });
});
