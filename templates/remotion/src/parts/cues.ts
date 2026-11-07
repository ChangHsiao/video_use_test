// 時間查詢：用字幕文字查 cues.json（align_voice.py 的輸出），得到「念到這句時」是這段動畫的第幾格
//
// 算繪時加 --public-dir ..（指到放 cues.json 的 edit/），程式就讀得到 cues.json。
// 配音重做 → 重跑 align_voice.py → 重新算繪，動畫自動跟上，不用改程式。

import {useEffect, useState} from 'react';
import {cancelRender, continueRender, delayRender, staticFile, useVideoConfig} from 'remotion';

type Cue = {start: number; end: number; show: string; say: string};

let cache: Promise<Cue[]> | null = null;

// 讀 cues.json，整段算繪只讀一次
const loadCues = (file: string) => {
  if (!cache) {
    cache = fetch(staticFile(file)).then((r) => {
      if (!r.ok) throw new Error(`讀不到 ${file}：算繪時要加 --public-dir 指到放 cues.json 的資料夾`);
      return r.json();
    });
  }
  return cache;
};

// 比對前拿掉空白和標點，「而且 它還會飛」和「而且，它還會飛。」才對得起來
const normalize = (s: string) => s.replace(/[\s 　，。；：？！、,.;:?!「」『』（）()"'“”‘’…—-]/g, '');

// 找出包含這段文字的那一句字幕；找不到或找到好幾句都直接報錯，避免動畫悄悄對錯時間
export const findCue = (cues: Cue[], text: string): Cue => {
  const key = normalize(text);
  const hits = cues.filter((c) => normalize(c.show).includes(key) || normalize(c.say).includes(key));
  if (hits.length === 0) throw new Error(`cues.json 裡找不到字幕「${text}」`);
  if (hits.length > 1) throw new Error(`cues.json 有 ${hits.length} 句字幕都含「${text}」，請寫長一點`);
  return hits[0];
};

// 回傳 at(文字)：那句字幕開始時，是這段動畫的第幾格。from 是這段動畫從哪裡開始：秒數，或「第一句字幕的文字」
// 注意：短字幕會被合併，查到的是「包含這段文字的那句字幕」的開始時間
export const useCueTimer = (from: number | string, file = 'cues.json') => {
  const {fps} = useVideoConfig();
  const [cues, setCues] = useState<Cue[] | null>(null);
  const [handle] = useState(() => delayRender(`讀取 ${file}`));
  useEffect(() => {
    loadCues(file).then((c) => { setCues(c); continueRender(handle); }).catch((e) => cancelRender(e));
  }, [file, handle]);
  if (cues === null) {
    // 還沒讀到時先回傳一個很大的格數，畫面上什麼都不出現；讀到後 Remotion 才會真的截圖
    return (_text: string, _offsetSec = 0) => 1e9;
  }
  const startSec = typeof from === 'number' ? from : findCue(cues, from).start;
  return (text: string, offsetSec = 0) => Math.round((findCue(cues, text).start + offsetSec - startSec) * fps);
};
