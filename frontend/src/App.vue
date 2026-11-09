<template>
  <router-view />
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
  padding: 0;
}

/* 稽查(jcxt)系列表单弹窗：输入框高度与「工单信息录入」弹窗对齐为 32px。
   页面用 el-form size="small" 时 Element Plus 默认 24px；这里只调高度与行高，
   圆角、边框、配色保持 jcxt 原样。弹窗 teleport 到 body，故写在全局样式里。 */
.jc-form-dialog .el-input__wrapper,
.jc-form-dialog .el-select__wrapper {
  min-height: 32px !important;
  height: 32px;
  /* Element Plus 这里默认 content-box,不设 border-box 会被上下 1px padding 撑成 34px */
  box-sizing: border-box;
}
.jc-form-dialog .el-form-item__label {
  height: 32px;
  line-height: 32px;
}
.jc-form-dialog .el-form-item__content {
  line-height: 32px;
}

/* ===== 通用表单弹窗基类 .std-dialog =====
   与 Gongdan(.gd-dialog) / Overtime(.ot-dialog) 同一套视觉:52px 紫题头贴顶贴边
   + 14px 上圆角、灰底无边框白卡、32px 胶囊控件、56px 白底按钮栏。
   任何模块的表单弹窗挂 class="std-dialog" 即可复用;el-dialog teleport 到 body,
   所以规则必须写在全局(非 scoped)并用类名前缀,页面级选择器够不到。 */
.std-dialog {
  --std-purple: #533afd;
  --el-color-primary: #533afd; /* 弹窗内按钮/选中/focus 与题头同色系 */
  padding: 0 !important; /* 抵消 el-dialog 四周内边距,题头/灰底/按钮栏全部贴边 */
  border-radius: 14px !important;
  overflow: hidden !important;
  background: #f3f2f0;
  box-shadow: 0 16px 28px rgba(16, 24, 40, .22), 0 2px 6px rgba(16, 24, 40, .08) !important;
}
.std-dialog .el-dialog__header {
  position: relative; /* 关闭钮 absolute 的基准 */
  height: 52px; box-sizing: border-box;
  display: flex; align-items: center; justify-content: center;
  margin: 0 !important; width: 100%; padding: 0 16px !important;
  background: var(--std-purple) !important;
  border-radius: 14px 14px 0 0 !important;
}
.std-dialog .el-dialog__title {
  color: #fff; font-size: 16px; font-weight: 600; letter-spacing: 1px; line-height: 52px;
}
.std-dialog .el-dialog__headerbtn {
  top: 50% !important; right: 10px !important; transform: translateY(-50%);
  width: 20px; height: 20px; border-radius: 50%; background: #fff;
  box-shadow: 0 1px 3px rgba(28, 30, 84, .35);
}
.std-dialog .el-dialog__headerbtn:hover { background: #e9e4ff !important; }
.std-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--std-purple) !important; font-size: 12px;
}
.std-dialog .el-dialog__body {
  padding: 10px 14px 8px !important; background: #f3f2f0;
}
.std-dialog .el-dialog__footer {
  min-height: 56px; box-sizing: border-box;
  /* flex 垂直居中:只写 min-height 按钮会贴在按钮栏顶部 */
  display: flex; align-items: center; justify-content: flex-end; gap: 8px;
  padding: 0 16px !important; background: #fff;
  border-top: 1px solid #efedea !important;
}
.std-dialog .el-dialog__footer > div { flex: 1 1 auto; min-width: 0; }
.std-dialog .el-dialog__footer .el-button {
  height: 32px; margin: 0; padding: 0 12px; border-radius: 8px; font-size: 13px;
}
.std-dialog .el-dialog__footer .el-button:not([class*="el-button--"]) {
  background: #fff; border-color: #e0dcd7; color: #3d3a35;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
}
.std-dialog .el-dialog__footer .el-button:not([class*="el-button--"]):hover {
  background: #faf9f7; border-color: #cfcabf; color: #3d3a35;
}
.std-dialog .el-dialog__footer .el-button--primary:not(.is-plain),
.std-dialog .el-dialog__footer .el-button--primary:not(.is-plain):hover {
  background: linear-gradient(135deg, #6a55ff, #533afd) !important;
  border-color: #4a33e0 !important; color: #fff !important;
  box-shadow: 0 2px 8px rgba(83, 58, 253, .32);
}

/* 灰底上的无边框白卡(同 .gd-card) */
.std-dialog .el-dialog__body > .el-form,
.std-dialog .el-dialog__body > .preview-body {
  background: #fff; border: none; border-radius: 12px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 4px 14px rgba(16, 24, 40, .05);
}

/* 控件:32px 高、16px 胶囊。⚠️ .el-input__wrapper 默认 content-box,
   不加 border-box 会被上下 padding 撑成 34px。不覆盖 padding:日期框前缀图标、
   input-number 加减钮依赖各自默认内边距;textarea 不设固定高。 */
.std-dialog .el-input__wrapper,
.std-dialog .el-select__wrapper {
  min-height: 32px !important; height: 32px; box-sizing: border-box;
  border-radius: 16px !important; background: #fff;
  box-shadow: 0 0 0 1px #ddd9d3 inset !important;
}
.std-dialog .el-input__wrapper:hover,
.std-dialog .el-select__wrapper:hover,
.std-dialog .el-input__wrapper.is-focus,
.std-dialog .el-select__wrapper.is-focused {
  box-shadow: 0 0 0 1px var(--std-purple) inset, 0 0 5px rgba(83, 58, 253, .25) !important;
}
.std-dialog .el-input__inner,
.std-dialog .el-select__placeholder {
  height: 30px; line-height: 30px; font-size: 13px; color: #1b1d21;
}
/* 已选值保持深色;未选值占位提示灰色 */
.std-dialog .el-select__placeholder.is-transparent,
.std-dialog .el-input__inner::placeholder {
  color: var(--el-text-color-placeholder, #a8abb2);
}
.std-dialog .el-textarea__inner {
  border-radius: 8px !important; padding: 8px 10px;
  font-size: 13px; line-height: 1.6; color: #1b1d21;
  box-shadow: 0 0 0 1px #ddd9d3 inset !important;
}
.std-dialog .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px var(--std-purple) inset, 0 0 6px rgba(83, 58, 253, .4) !important;
}
.std-dialog .el-form-item { margin-bottom: 12px; }
.std-dialog .el-form-item__label {
  height: 32px; line-height: 32px;
  color: #5a5752; font-size: 13px; font-weight: 500;
}
.std-dialog .el-form-item__content { min-height: 32px; line-height: 32px; }
.std-dialog .preview-nav .el-button { height: 32px; border-radius: 8px; }
</style>
