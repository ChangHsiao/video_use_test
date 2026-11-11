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

// 找字幕，回傳第幾句（從 0 算），規則同 helpers/compose.py：只找 after 那句之後的字幕；整句完全相同的優先；
// 只是包含又有好幾句符合就報錯，避免動畫悄悄對錯時間。
// mustBeOnly：動畫的起點沒有「上一句」可以參考，整句相同的出現好幾次時也要報錯，請使用者在前面加一句
export const findCue = (cues: Cue[], text: string, after = -1, mustBeOnly = false): number => {
  const key = normalize(text);
  const hits: number[] = [];
  for (let i = after + 1; i < cues.length; i++) {
    if (key && (normalize(cues[i].show).includes(key) || normalize(cues[i].say).includes(key))) hits.push(i);
  }
  const exact = hits.filter((i) => normalize(cues[i].show) === key || normalize(cues[i].say) === key);
  if (exact.length > 1 && mustBeOnly) {
    const second = exact[1];
    const before = second > 0 ? cues[second - 1].show : '前一句的文字';
    throw new Error(`「${text}」出現了 ${exact.length} 次（第 ${exact.map((i) => i + 1).join('、')} 句），`
      + `請在前面加一句，例如 ['${before}', '${text}']`);
  }
  if (exact.length > 0) return exact[0];
  const where = after < 0 ? '' : `在第 ${after + 1} 句字幕之後`;
  if (hits.length === 0) throw new Error(`cues.json ${where}找不到字幕「${text}」`);
  if (hits.length > 1) throw new Error(`cues.json 有 ${hits.length} 句字幕都含「${text}」，請寫長一點`);
  return hits[0];
};

// 找動畫起點那一句：寫一句時，那句在整支片只能出現一次；寫兩句 ['A', 'B'] 時，從 A 之後找 B
const findStart = (cues: Cue[], from: string | [string, string]): number => {
  if (typeof from === 'string') return findCue(cues, from, -1, true);
  return findCue(cues, from[1], findCue(cues, from[0], -1, true));
};

// 回傳 at(文字)：那句字幕開始時，是這段動畫的第幾格。from 是這段動畫從哪裡開始：
// 秒數、「第一句字幕的文字」，或第一句和整支片裡重複時寫成 ['它的前一句', '第一句']。
// at(文字) 只從起點那句往後找，所以起點之前出現過的同一句不會被找到。
// 注意：短字幕會被合併，查到的是「包含這段文字的那句字幕」的開始時間
export const useCueTimer = (from: number | string | [string, string], file = 'cues.json') => {
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
  // 起點是秒數時，從起點之前最後一句的下一句開始找
  const startIdx = typeof from === 'number' ? cues.filter((c) => c.start < from).length : findStart(cues, from);
  const startSec = typeof from === 'number' ? from : cues[startIdx].start;
  return (text: string, offsetSec = 0) =>
    Math.round((cues[findCue(cues, text, startIdx - 1)].start + offsetSec - startSec) * fps);
};
