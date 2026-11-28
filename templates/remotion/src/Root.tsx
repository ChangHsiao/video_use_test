// 動畫清單：每段動畫在這裡登記一個 Composition（id、長度、尺寸）；做新動畫時加一行，不用的範例可以刪掉
import React from 'react';
import {Composition} from 'remotion';
import {Boiling} from './examples/Boiling';
import {O1} from './brands/桑尼資料科學/outro/O1';

// shown only when a render forgot --props, so the mistake is visible instead of silently using old text
const OUTRO_TEXT_MISSING = {name: '（缺 --props）', nameEn: 'missing --props', slogan: '（缺 --props：slogan）',
  footer: '（缺 --props：footer）'};

// 直式 1080×1920、30fps；durationInFrames = 這段動畫的秒數 × 30
export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Boiling" component={Boiling} durationInFrames={210} fps={30} width={1080} height={1920} />
    {/* 品牌片尾 A（數據流）。文字不寫在這裡：算繪時用 --props 傳入 helpers/outro_props.py 從 brand.json 產生的內容 */}
    <Composition id="OutroA-4s" component={O1} durationInFrames={120} fps={30} width={1080} height={1920}
      defaultProps={{speed: 1, ...OUTRO_TEXT_MISSING}} />
    <Composition id="OutroA-3s" component={O1} durationInFrames={90} fps={30} width={1080} height={1920}
      defaultProps={{speed: 4 / 3, ...OUTRO_TEXT_MISSING}} />
  </>
);
