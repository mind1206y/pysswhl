// 把后端返回的扁平部门列表组装成树形结构(el-table / el-tree-select 通用)
export function buildDeptTree(list) {
  const map = new Map(list.map((d) => [d.id, { ...d, children: [] }]))
  const roots = []
  for (const node of map.values()) {
    const parent = node.parent_id ? map.get(node.parent_id) : null
    if (parent) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  }
  // 没有子级的节点去掉 children 字段,避免表格渲染出多余的展开箭头
  for (const node of map.values()) {
    if (!node.children.length) delete node.children
  }
  return roots
}
