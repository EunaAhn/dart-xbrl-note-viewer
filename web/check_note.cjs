// 표 렌더링 자가 점검: node web/check_note.cjs
// index.html의 순수 함수(axisInfo, gridTable 등)를 꺼내 작은 픽스처로 돌린다.
const fs = require('fs'), assert = require('assert');
const src = fs.readFileSync(__dirname + '/viewer.html', 'utf8');
const pick = n => src.match(new RegExp(`function ${n}\\([\\s\\S]*?\\n}\\n`))[0];
const isNum = v => /^-?\d+(\.\d+)?$/.test(v), fmt = v => Number(v).toLocaleString('ko-KR');
const L = n => n.korean_label, S = n => n.korean_std || L(n), prop = eid => eid ? ` data-eid="${eid}"` : '';
const out = {}, summary = {};
const document = { createElement: () => (out.card = { querySelector: s => s === '.tables' ? out : s === '.psel' ? {} : summary,
  querySelectorAll: () => [{ value: 'CFY2026eHYA' }] }) };
const SCOPE_AXIS = /ConsolidatedAndSeparateFinancialStatementsAxis$/;
eval(['esc', 'cell', 'periodName', 'headerAxes', 'foldInstants', 'axisInfo', 'noteCard', 'gridTable', 'emptyColumns'].map(pick).join('\n'));

const node = (id, label, children = []) => ({ element_id: id, korean_label: label, children });
const roots = [node('Abstract', '공시 [개요]', [
  node('XTable', '공시 [표]', [node('CAxis', '금액 [축]', [node('CarryingMember', '장부금액', [node('ReportedMember', '공시금액')])])]),
  node('XLineItems', '공시 [항목]', [node('A', '유동자산', [node('A1', '선급금')])]),
]), node('CSTable', '연결 [표]', [node('ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis', '연결/별도 [축]', [node('CSDomain', '도메인', [node('Cons', '연결')])])])];
const byId = {};
const index = (n, p) => { n.parent = p; byId[n.element_id] ??= n; n.children.forEach(c => index(c, n)); };
roots.forEach(r => index(r, null));

const col = (ctx, dims, period = '2026-06-30') => ({ contextId: ctx, period, members: dims.map(d => d[1]),
                               dims: dims.map(([axis, member]) => ({ axis, member })) });
const cons = ['ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis', 'Cons'], rep = ['CAxis', 'ReportedMember'];
const t = { title: '공시 [항목]', elementId: 'XLineItems', columns: [
  col('CFY2026eHYA_c', [cons]), col('CFY2026eHYA_cr', [cons, rep]), col('CFY2026eHYA_cc', [cons, ['CAxis', 'CarryingMember']])],
  rows: [{ label: '유동자산', depth: 0, cells: { CFY2026eHYA_c: '1001', CFY2026eHYA_cr: '1000', CFY2026eHYA_cc: '999' } },
         { label: '선급금', depth: 1, cells: { CFY2026eHYA_cr: '-400' } }] };

noteCard(t, byId, axisInfo(roots));
const html = out.innerHTML;
assert.equal(summary.textContent, '당반기말');
assert.ok(!html.includes('연결/별도 [축]'), '연결/별도 축은 머리글에서 빠진다');
assert.deepEqual(headerAxes([col('x', [cons, rep]), col('y', [cons, rep])], axisInfo(roots)), ['CAxis'], '멤버가 하나뿐인 축도 머리글에 남는다');
assert.ok(!html.includes('999'), '하위 멤버(공시금액) 열이 있으면 상위 멤버(장부금액) 열은 뺀다');
assert.ok(html.includes('rowspan="2">장부금액 [합계]'), '축 없는 컨텍스트는 [합계] 열');
assert.ok(html.includes('<td class="row-label row-group-cell" rowspan="2" data-eid="XLineItems">공시 [항목]</td><td class="row-label row-group-cell" colspan="2">유동자산</td><td class="num">1,000</td><td class="num">1,001</td>'));
assert.ok(html.includes('<td class="row-label row-group-cell" rowspan="1">유동자산</td><td class="row-label row-group-cell" colspan="1">선급금</td><td class="num neg">(400)</td><td></td>'), '음수는 괄호');

// 빈 열 표시: 큐브의 최하위 멤버(공시금액)만 열이 되고, 상위 멤버(장부금액)·연결/별도 축은 열을 안 만든다.
// 이미 있는 [합계](축 없는 열)는 다시 만들지 않는다.
const cube = { CAxis: ['CarryingMember', 'ReportedMember'], 'ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis': ['Cons'] };
const empty = emptyColumns(cube, [col('CFY2026eHYA_x', [cons])], axisInfo(roots));
assert.deepEqual(empty.map(c => c.dims.map(d => d.member).join()), ['ReportedMember']);
assert.equal(empty[0].contextId.split('_')[0], 'CFY2026eHYA');

assert.equal(periodName('PFY2025eHY_x'), '전기말');
assert.equal(periodName('CFY2026dFY'), '당기');
assert.equal(periodName('CFY2026dHYQ'), '당반기 3개월');
assert.equal(periodName('PFY2025dHYA'), '전반기 누적');
assert.equal(periodName('CFY2026eQ1A'), '당분기말');

// 현금흐름표: 기초 현금(전기말 시점)과 기말 현금(당반기말 시점)이 당반기 누적 열로 들어간다.
const f = foldInstants({ columns: [col('CFY2026dHYA_c', [cons], '2026-01-01 ~ 2026-06-30'),
    col('CFY2026eHYA_c', [cons]), col('PFY2025eHY_c', [cons], '2025-12-31')],
  rows: [{ label: '영업활동', cells: { CFY2026dHYA_c: '5' } },
         { label: '기초현금', labelRole: 'http://www.xbrl.org/2003/role/periodStartLabel', cells: { PFY2025eHY_c: '10', CFY2026eHYA_c: '15' } },
         { label: '기말현금', labelRole: 'http://www.xbrl.org/2003/role/periodEndLabel', cells: { PFY2025eHY_c: '10', CFY2026eHYA_c: '15' } }] });
assert.deepEqual(f.columns.map(c => c.contextId), ['CFY2026dHYA_c']);
assert.deepEqual(f.rows.map(r => r.cells.CFY2026dHYA_c), ['5', '10', '15']);
console.log('ok');
