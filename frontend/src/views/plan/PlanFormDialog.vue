<script setup>
import { computed, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CATEGORIES, MIDDLE_CATEGORIES, LEIBIE_OPTIONS, money, tzInfo } from './common'

const props = defineProps({
  modelValue: Boolean,
  initial: Object,
  dicts: Object,
  mode: { type: String, default: 'todo' }, // todo | summary
  editing: Boolean,
})
const emit = defineEmits(['update:modelValue', 'save', 'return'])

const form = reactive({
  niandu: null, jhlb: '更新改造', ssbm: null, zb: null, zgy: '', leibie: '',
  xuhao: '', daibanname: '', jine: null, startjine: null, zongtouzi: null,
  kgny: '', jgny: '', xjxl: '', bz: '', pizhu: '',
})

const isMiddle = computed(() => MIDDLE_CATEGORIES.includes(form.jhlb))
const isGxgz = computed(() => form.jhlb === '更新改造')

watch(() => props.modelValue, (open) => {
  if (!open) return
  const d = props.initial || {}
  Object.assign(form, {
    niandu: d.niandu ?? props.dicts.default_year,
    jhlb: d.jhlb || props.dicts.categories?.[0] || '更新改造',
    ssbm: d.bumenid ?? d.ssbm ?? props.dicts.departments?.[0]?.id ?? null,
    zb: d.Ezb ?? d.zb_id ?? d.zb ?? props.dicts.hosts?.[0]?.id ?? null,
    zgy: d.zhuanguan || d.zgy || '',
    leibie: d.leibie || '',
    xuhao: d.xuhao || '',
    daibanname: d.daibanname || '',
    jine: d.jine ?? null,
    startjine: d.startjine ?? null,
    zongtouzi: d.zongtouzi ?? null,
    kgny: d.kgny || '',
    jgny: d.jgny || '',
    xjxl: d.xjxl || '',
    bz: d.bz || '',
    pizhu: d.pizhu || '',
  })
  if (typeof form.zb === 'string') {
    const host = (props.dicts.hosts || []).find((h) => h.name === form.zb)
    form.zb = host ? host.id : null
  }
})

function payload(extra = {}) {
  return {
    niandu: form.niandu, jhlb: form.jhlb, ssbm: form.ssbm, zb: form.zb,
    zgy: form.zgy, leibie: form.leibie, xuhao: form.xuhao,
    daibanname: form.daibanname, jine: form.jine, startjine: form.startjine,
    zongtouzi: form.zongtouzi, kgny: form.kgny, jgny: form.jgny,
    xjxl: form.xjxl, bz: form.bz, pizhu: form.pizhu, ...extra,
  }
}

function validate() {
  if (!form.ssbm) return ElMessage.warning('请选择所属部门'), false
  if (!form.zb) return ElMessage.warning('请选择主办部门'), false
  if (!form.zgy) return ElMessage.warning('请选择专管员'), false
  if (!form.leibie) return ElMessage.warning('请选择小类别'), false
  if (!form.daibanname) return ElMessage.warning('请输入项目名称'), false
  if (form.jine === null || form.jine === undefined) return ElMessage.warning('请输入项目计划总投资'), false
  return true
}

function submit(action) {
  if (!validate()) return
  emit('save', payload(), action)
}

function tz() {
  return tzInfo({ jine: form.jine, startjine: form.startjine })
}

defineExpose({ payload })
</script>

<template>
  <el-dialog :model-value="modelValue" :title="editing ? '编辑计划' : '添加计划'"
    width="980px" :close-on-click-modal="false" class="std-dialog" @update:model-value="emit('update:modelValue', $event)">
    <el-form label-width="126px" class="plan-form">
      <div class="form-grid">
        <el-form-item label="计划类别" class="span2">
          <el-radio-group v-model="form.jhlb">
            <el-radio-button v-for="c in dicts.categories || CATEGORIES" :key="c" :label="c">{{ c }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="!editing" label="年度">
          <el-select v-model="form.niandu" style="width: 100%">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="年度">
          <el-input :model-value="form.niandu" disabled />
        </el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="form.ssbm" filterable style="width: 100%">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="主办部门">
          <el-select v-model="form.zb" filterable style="width: 100%">
            <el-option v-for="d in dicts.hosts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="专管员">
          <el-select v-model="form.zgy" filterable allow-create default-first-option
            style="width: 100%" placeholder="选择或输入姓名">
            <el-option v-for="z in dicts.zgys" :key="z" :label="z" :value="z" />
          </el-select>
        </el-form-item>
        <el-form-item label="小类别">
          <el-select v-model="form.leibie" style="width: 100%">
            <el-option v-for="l in dicts.leibie || LEIBIE_OPTIONS" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="序号">
          <el-input v-model="form.xuhao" placeholder="如 3.33" />
        </el-form-item>
        <el-form-item v-if="isGxgz" label="新建/续建">
          <el-select v-model="form.xjxl" clearable style="width: 100%">
            <el-option label="新建" value="新建" />
            <el-option label="续建" value="续建" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目名称" class="span2">
          <el-input v-model="form.daibanname" />
        </el-form-item>
        <el-form-item label="计划总投资(万)">
          <el-input-number v-model="form.jine" :precision="2" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="isGxgz" label="本年投资(万)">
          <el-input-number v-model="form.zongtouzi" :precision="2" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="isGxgz" label="开工年月">
          <el-date-picker v-model="form.kgny" type="month" value-format="YYYY-MM" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="isGxgz" label="竣工年月">
          <el-date-picker v-model="form.jgny" type="month" value-format="YYYY-MM" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="isMiddle" label="年初金额(万)">
          <el-input-number v-model="form.startjine" :precision="2" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="isMiddle" label="调增/调减">
          <span :style="{ color: tz()?.color || '#999', fontWeight: 600 }">{{ tz()?.text || '—' }}</span>
        </el-form-item>
        <el-form-item label="批注">
          <el-input v-model="form.pizhu" />
        </el-form-item>
        <el-form-item label="项目说明" class="span2">
          <el-input v-model="form.bz" type="textarea" :rows="8" />
        </el-form-item>
        <el-form-item v-if="editing && dicts.__opname" label="上报员">
          <el-input :model-value="dicts.__opname" disabled />
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button v-if="editing && mode === 'summary'" type="danger" plain @click="emit('return', payload())">
        回退营业所
      </el-button>
      <el-button @click="submit('save')">保存</el-button>
      <el-button v-if="mode === 'todo'" type="primary" @click="submit('submit')">
        {{ editing ? '保存并提交汇总' : '直接提交汇总' }}
      </el-button>
      <el-button v-else-if="editing" type="primary" @click="submit('approve')">保存且通过计划</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 18px; }
.span2 { grid-column: span 2; }
.plan-form :deep(.el-form-item) { margin-bottom: 12px; }
</style>
