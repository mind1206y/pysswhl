<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '' },
  showSms: { type: Boolean, default: true },
  smsLabel: { type: String, default: '' },
  showComment: { type: Boolean, default: false },
  commentLabel: { type: String, default: '批注' },
  commentPlaceholder: { type: String, default: '可填写批注（选填）' },
  confirmText: { type: String, default: '确定' },
  type: { type: String, default: 'info' },
})

const emit = defineEmits(['update:modelValue', 'confirm'])
const state = reactive({ sms: false, comment: '' })

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      state.sms = false
      state.comment = ''
    }
  },
)

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  emit('update:modelValue', false)
  emit('confirm', { sms: state.sms, comment: state.comment.trim() })
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="430px" append-to-body class="std-dialog"
    @update:model-value="emit('update:modelValue', $event)">
    <el-form class="sms-form" label-width="52px">
      <p class="sms-message">{{ message }}</p>
      <el-form-item v-if="showComment" :label="commentLabel">
        <el-input v-model="state.comment" type="textarea" :rows="2"
          :placeholder="commentPlaceholder" maxlength="500" show-word-limit />
      </el-form-item>
      <el-checkbox v-if="showSms" v-model="state.sms" class="sms-check">
        短信通知{{ smsLabel }}
      </el-checkbox>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" @click="confirm">{{ confirmText }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.sms-message { margin: 0 0 14px; font-size: 15px; color: #1c1e54; }
.sms-form { margin-bottom: 4px; }
.sms-check { margin-top: 4px; font-size: 14px; }
</style>
