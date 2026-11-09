import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import ElementPlus, { ElDatePicker } from 'element-plus'

const Comp = {
  render() {
    return h('div', { class: 'filter-row' }, [
      h(ElDatePicker, {
        class: 'leak-date-range',
        type: 'daterange',
        modelValue: ['2026-01-01', '2026-12-31'],
        'value-format': 'YYYY-MM-DD',
        'range-separator': '至',
      }),
    ])
  },
  __scopeId: 'data-v-test123',
}

const app = createSSRApp({ render: () => h(Comp) })
app.use(ElementPlus)
const html = await renderToString(app)
console.log(html)
