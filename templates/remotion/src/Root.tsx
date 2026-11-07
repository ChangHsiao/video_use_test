// 動畫清單：每段動畫在這裡登記一個 Composition（id、長度、尺寸）；做新動畫時加一行，不用的範例可以刪掉
import React from 'react';
import {Composition} from 'remotion';
import {Boiling} from './examples/Boiling';

// 直式 1080×1920、30fps；durationInFrames = 這段動畫的秒數 × 30
export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Boiling" component={Boiling} durationInFrames={210} fps={30} width={1080} height={1920} />
  </>
);
