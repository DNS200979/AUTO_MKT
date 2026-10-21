import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { supabase } from './supabase'

const demoOverview = {
  customers_by_status: { ACTIVE: 18, PENDING: 3, BLOCKED: 1 },
  payments_by_status: { PAID: 24, PENDING: 2, DECLINED: 1 },
  open_debts: { count: 2, amount_cents: 26440 },
  failed_notifications: 1,
  generated_at: new Date().toISOString(),
  recent_events: [
    { event_id: 'evt-1', event_type: 'PaymentApproved', resource_id: 'PAY-1548', occurred_at: '2025-05-20T09:37:12Z' },
    { event_id: 'evt-2', event_type: 'AccessAuthorized', resource_id: 'ACC-8831', occurred_at: '2025-05-20T09:21:45Z' },
    { event_id: 'evt-3', event_type: 'DebtRegistered', resource_id: 'PAY-0231', occurred_at: '2025-05-20T08:58:03Z' },
    { event_id: 'evt-4', event_type: 'NotificationFailed', resource_id: 'NTF-7721', occurred_at: '2025-05-20T08:47:19Z' },
    { event_id: 'evt-5', event_type: 'PaymentApproved', resource_id: 'PAY-1547', occurred_at: '2025-05-20T08:16:34Z' },
    { event_id: 'evt-6', event_type: 'AccessAuthorized', resource_id: 'ACC-8829', occurred_at: '2025-05-20T07:59:11Z' },
    { event_id: 'evt-7', event_type: 'SystemStarted', resource_id: 'SYS-001', occurred_at: '2025-05-20T07:32:08Z' },
  ],
}

const navItems = [
  { label: 'Visão da operação', icon: 'grid' },
  { label: 'Acessos', icon: 'door' },
  { label: 'Pagamentos', icon: 'card' },
  { label: 'Dívidas abertas', icon: 'debt' },
  { label: 'Notificações', icon: 'bell' },
]

const eventMeta = {
  PaymentApproved: { title: 'Pagamento aprovado', detail: 'Pagamento confirmado pelo provedor', tone: 'success', label: 'Pagamentos' },
  AccessAuthorized: { title: 'Acesso realizado', detail: 'Cliente autorizado a entrar na loja', tone: 'success', label: 'Acessos' },
  AccessDenied: { title: 'Acesso recusado', detail: 'Solicitação de entrada recusada pelas regras da operação', tone: 'warning', label: 'Acessos' },
  DoorOpened: { title: 'Porta aberta', detail: 'Controlador confirmou a abertura da porta', tone: 'success', label: 'Acessos' },
  DoorOpenFailed: { title: 'Falha ao abrir a porta', detail: 'O controlador não confirmou a abertura', tone: 'danger', label: 'Acessos' },
  DebtRegistered: { title: 'Dívida registrada', detail: 'Pagamento pendente requer atenção', tone: 'warning', label: 'Dívidas' },
  NotificationFailed: { title: 'Falha no envio da notificação', detail: 'A entrega será reprocessada pelo worker', tone: 'danger', label: 'Notificações' },
  SystemStarted: { title: 'Sistema iniciado', detail: 'Serviços da loja iniciados automaticamente', tone: 'neutral', label: 'Sistema' },
}

const paymentStatusLabels = {
  CREATED: 'Criado',
  PROCESSING: 'Processando',
  PAID: 'Pago',
  DECLINED: 'Recusado',
  PENDING: 'Pendente',
  RETRY: 'Nova tentativa',
  UNPAID: 'Em aberto',
  REFUNDED: 'Estornado',
  DISPUTED: 'Contestação',
}

const paymentStatusOptions = Object.entries(paymentStatusLabels)
const debtStatusOptions = ['DECLINED', 'PENDING', 'RETRY', 'UNPAID'].map((status) => [status, paymentStatusLabels[status]])

function Icon({ name, size = 20 }) {
  const paths = {
    grid: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    door: <><path d="M6 20V4a2 2 0 0 1 2-2h10v18" /><path d="M4 20h17" /><path d="M13 11h.01" /></>,
    card: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18" /><path d="M7 15h4" /></>,
    debt: <><path d="M12 3v18" /><path d="M17 7.5c-.8-1-2.1-1.5-4-1.5-2.3 0-4 1.1-4 2.8 0 4.4 8 1.9 8 6.4 0 1.8-1.7 2.8-4 2.8-1.9 0-3.2-.5-4-1.5" /><path d="M5 3h14v18H5z" opacity=".25" /></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
    refresh: <><path d="M20 11a8 8 0 0 0-14.6-4L3 10" /><path d="M3 5v5h5" /><path d="M4 13a8 8 0 0 0 14.6 4L21 14" /><path d="M21 19v-5h-5" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    alert: <><path d="M10.3 3.9 2.2 18a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
    shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  }
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function formatTime(value) {
  return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function formatDate(value) {
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(value))
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function money(cents) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100)
}

function eventPresentation(event) {
  const meta = eventMeta[event.event_type] || { title: event.event_type, detail: 'Evento registrado na auditoria', tone: 'neutral', label: 'Sistema' }
  return { ...meta, time: formatTime(event.occurred_at), date: formatDate(event.occurred_at) }
}

function StatusBand({ overview }) {
  const normal = (overview.failed_notifications || 0) === 0
  return <section className="status-band" aria-label="Status da loja">
    <div className={`status-mark ${normal ? 'is-good' : 'is-alert'}`}><Icon name={normal ? 'check' : 'alert'} size={34} /></div>
    <div className="store-status"><h2>Mercadinho Central</h2><p className={normal ? 'good-text' : 'danger-text'}>{normal ? 'Tudo operacional' : 'Requer atenção'}</p></div>
    <div className="status-divider" />
    <Metric icon="user" value={overview.customers_by_status?.ACTIVE || 0} label="Clientes ativos" tone="good" />
    <Metric icon="card" value={overview.payments_by_status?.PAID || 0} label="Pagamentos" tone="good" />
    <Metric icon="debt" value={overview.open_debts?.count || 0} label="Dívidas abertas" tone="warning" />
    <Metric icon="bell" value={overview.failed_notifications || 0} label="Notificações" tone={overview.failed_notifications ? 'danger' : 'good'} />
  </section>
}

function Metric({ icon, value, label, tone }) {
  return <div className="metric"><div className={`metric-icon ${tone}`}><Icon name={icon} size={21} /></div><div><strong>{value}</strong><span>{label}</span><small className={`${tone}-text`}>{tone === 'danger' ? 'Requer atenção' : tone === 'warning' ? 'Atenção' : 'Tudo normal'}</small></div></div>
}

function EventTimeline({ events, filter, onFilter }) {
  const filtered = filter === 'Todos' ? events : events.filter((event) => eventPresentation(event).label === filter)
  return <section className="panel timeline-panel">
    <div className="panel-heading"><div><h3>Eventos recentes</h3><p>O que está acontecendo na operação</p></div><select value={filter} onChange={(event) => onFilter(event.target.value)} aria-label="Filtrar eventos"><option>Todos</option><option>Acessos</option><option>Pagamentos</option><option>Dívidas</option><option>Notificações</option><option>Sistema</option></select></div>
    <div className="timeline">{filtered.map((event) => { const item = eventPresentation(event); return <article className="timeline-item" key={event.event_id}><div className={`timeline-node ${item.tone}`}><Icon name={item.tone === 'success' ? 'check' : item.tone === 'danger' || item.tone === 'warning' ? 'alert' : 'grid'} size={15} /></div><div className="event-date"><span>{item.date}</span><strong>{item.time}</strong></div><div className="event-copy"><strong>{item.title}</strong><span>{item.detail} · {event.resource_id}</span></div><span className={`event-tag ${item.tone}`}>{item.label}</span></article> })}</div>
    {filtered.length === 0 && <div className="empty-state">Nenhum evento neste filtro.</div>}
    <button className="text-button" type="button" onClick={() => onFilter('Todos')}>Ver todos os eventos <span>→</span></button>
  </section>
}

function AccessesPanel({ events }) {
  const accesses = events.filter((event) => eventMeta[event.event_type]?.label === 'Acessos')
  return <section className="panel timeline-panel">
    <div className="panel-heading"><div><h3>Registros de acesso</h3><p>Decisões e confirmações recentes do controlador da porta</p></div><span className="event-tag neutral">{accesses.length} registros</span></div>
    <div className="timeline">{accesses.map((event) => { const item = eventPresentation(event); return <article className="timeline-item" key={event.event_id}><div className={`timeline-node ${item.tone}`}><Icon name={item.tone === 'success' ? 'check' : item.tone === 'danger' || item.tone === 'warning' ? 'alert' : 'grid'} size={15} /></div><div className="event-date"><span>{item.date}</span><strong>{item.time}</strong></div><div className="event-copy"><strong>{item.title}</strong><span>{item.detail} · {event.resource_id}</span></div><span className={`event-tag ${item.tone}`}>{item.label}</span></article> })}</div>
    {accesses.length === 0 && <div className="empty-state">Nenhum evento de acesso registrado.</div>}
  </section>
}

function ComingSoonPanel({ section }) {
  return <section className="panel timeline-panel"><div className="panel-heading"><div><h3>{section}</h3><p>Esta área ainda não está conectada aos dados operacionais.</p></div></div><div className="empty-state">A próxima etapa vai disponibilizar esta consulta.</div></section>
}

function paymentStatusTone(status) {
  if (status === 'PAID') return 'success'
  if (status === 'DECLINED' || status === 'DISPUTED') return 'danger'
  if (['PENDING', 'RETRY', 'UNPAID'].includes(status)) return 'warning'
  return 'neutral'
}

function PaymentsPanel({ items, total, limit, offset, status, loading, error, onStatusChange, onPageChange, onRetry }) {
  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + items.length, total)
  return <section className="panel payments-panel">
    <div className="panel-heading"><div><h3>Pagamentos</h3><p>Transações recentes da operação, sem dados pessoais</p></div><div className="payments-controls"><label className="payment-filter">Estado<select value={status} onChange={(event) => onStatusChange(event.target.value)} aria-label="Filtrar pagamentos por estado"><option value="">Todos</option>{paymentStatusOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button className="payments-refresh" type="button" onClick={onRetry} disabled={loading}>{loading ? 'Atualizando…' : 'Atualizar'}</button></div></div>
    {error && <div className="payments-error" role="alert"><span>{error}</span><button type="button" onClick={onRetry}>Tentar novamente</button></div>}
    <div className="payments-table-wrap"><table className="payments-table"><thead><tr><th>Pagamento</th><th>Valor</th><th>Estado</th><th>Tentativas</th><th>Criado em</th><th>Atualizado em</th></tr></thead><tbody>
      {items.map((payment) => <tr key={payment.payment_id}><td><strong>{payment.payment_id}</strong><small>Compra {payment.purchase_id}</small></td><td className="payment-amount">{money(payment.amount_cents)}</td><td><span className={`payment-status ${paymentStatusTone(payment.status)}`}>{paymentStatusLabels[payment.status] || payment.status}</span></td><td>{payment.attempts}</td><td>{formatDateTime(payment.created_at)}</td><td>{formatDateTime(payment.updated_at)}</td></tr>)}
      {!loading && items.length === 0 && <tr><td colSpan="6" className="payments-empty">{status ? 'Nenhum pagamento encontrado para este estado.' : 'Nenhum pagamento registrado.'}</td></tr>}
      {loading && items.length === 0 && <tr><td colSpan="6" className="payments-empty">Carregando pagamentos…</td></tr>}
    </tbody></table></div>
    <div className="payments-pagination"><span>{loading ? 'Atualizando lista…' : `Exibindo ${firstItem}–${lastItem} de ${total}`}</span><div><button type="button" onClick={() => onPageChange(Math.max(0, offset - limit))} disabled={loading || offset === 0}>Anterior</button><button type="button" onClick={() => onPageChange(offset + limit)} disabled={loading || offset + limit >= total}>Próxima</button></div></div>
  </section>
}

function DebtsPanel({ items, total, totalAmountCents, limit, offset, status, loading, error, onStatusChange, onPageChange, onRetry }) {
  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + items.length, total)
  return <section className="panel payments-panel">
    <div className="panel-heading"><div><h3>Dívidas abertas</h3><p>{total} {total === 1 ? 'dívida' : 'dívidas'} · {money(totalAmountCents)} no total</p></div><div className="payments-controls"><label className="payment-filter">Estado<select value={status} onChange={(event) => onStatusChange(event.target.value)} aria-label="Filtrar dívidas por estado"><option value="">Todos</option>{debtStatusOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button className="payments-refresh" type="button" onClick={onRetry} disabled={loading}>{loading ? 'Atualizando…' : 'Atualizar'}</button></div></div>
    {error && <div className="payments-error" role="alert"><span>{error}</span><button type="button" onClick={onRetry}>Tentar novamente</button></div>}
    <div className="payments-table-wrap"><table className="payments-table"><thead><tr><th>Pagamento</th><th>Valor</th><th>Estado</th><th>Tentativas</th><th>Criado em</th><th>Atualizado em</th></tr></thead><tbody>
      {items.map((debt) => <tr key={debt.payment_id}><td><strong>{debt.payment_id}</strong><small>Compra {debt.purchase_id}</small></td><td className="payment-amount">{money(debt.amount_cents)}</td><td><span className={'payment-status ' + paymentStatusTone(debt.status)}>{paymentStatusLabels[debt.status] || debt.status}</span></td><td>{debt.attempts}</td><td>{formatDateTime(debt.created_at)}</td><td>{formatDateTime(debt.updated_at)}</td></tr>)}
      {!loading && !error && items.length === 0 && <tr><td colSpan="6" className="payments-empty">{status ? 'Nenhuma dívida encontrada para este estado.' : 'Nenhuma dívida aberta.'}</td></tr>}
      {loading && items.length === 0 && <tr><td colSpan="6" className="payments-empty">Carregando dívidas…</td></tr>}
    </tbody></table></div>
    <div className="payments-pagination"><span>{loading ? 'Atualizando lista…' : 'Exibindo ' + firstItem + '–' + lastItem + ' de ' + total}</span><div><button type="button" onClick={() => onPageChange(Math.max(0, offset - limit))} disabled={loading || offset === 0}>Anterior</button><button type="button" onClick={() => onPageChange(offset + limit)} disabled={loading || offset + limit >= total}>Próxima</button></div></div>
  </section>
}

function ActivityPanel({ overview, demo, onNavigate }) {
  const payments = [
    ['09:37', '#1548', 'Pix', 'R$ 78,50', 'Aprovado'],
    ['08:16', '#1547', 'Cartão', 'R$ 152,00', 'Aprovado'],
    ['07:12', '#1546', 'Pix', 'R$ 63,90', 'Aprovado'],
  ]
  const debts = [['#231', 'João Pereira', 'R$ 189,90', '2 dias', 'warning'], ['#230', 'Maria Santos', 'R$ 74,50', '1 dia', 'danger']]
  const paymentCount = Object.values(overview.payments_by_status || {}).reduce((sum, count) => sum + count, 0)
  return <section className="panel activity-panel">
    <div className="panel-heading"><div><h3>Atividade de pagamentos e dívidas</h3><p>Resumo da operação</p></div></div>
    <div className="activity-section">
      <div className="activity-title"><strong>Pagamentos <span>(total)</span></strong><button className="link-button" type="button" onClick={() => onNavigate('Pagamentos')}>Ver todos</button></div>
      {demo
        ? payments.map((payment) => <div className="payment-row" key={payment[1]}><span>{payment[0]}</span><strong>{payment[1]}</strong><span>{payment[2]}</span><b>{payment[3]}</b><em>{payment[4]}</em></div>)
        : paymentCount > 0
          ? <div className="activity-summary"><strong>{paymentCount} {paymentCount === 1 ? 'pagamento registrado' : 'pagamentos registrados'}</strong><span>Consulte a lista para ver estados e valores.</span></div>
          : <div className="activity-empty">Nenhum pagamento registrado.</div>}
    </div>
    <div className="activity-section">
      <div className="activity-title"><strong>Dívidas abertas <span>({overview.open_debts?.count || 0})</span></strong><button className="link-button" type="button" onClick={() => onNavigate('Dívidas abertas')}>Ver todas</button></div>
      {demo
        ? debts.map((debt) => <div className="debt-row" key={debt[0]}><strong>{debt[0]}</strong><span>{debt[1]}</span><b>{debt[2]}</b><em className={debt[4]}>{debt[3]}</em></div>)
        : overview.open_debts?.count > 0
          ? <div className="activity-summary"><strong>{money(overview.open_debts.amount_cents)} em aberto</strong><span>{overview.open_debts.count} {overview.open_debts.count === 1 ? 'dívida' : 'dívidas'} aguardando regularização.</span></div>
          : <div className="activity-empty">Nenhuma dívida aberta.</div>}
    </div>
    <div className="activity-section last">
      <div className="activity-title"><strong>Últimas notificações</strong><button className="link-button" type="button" onClick={() => onNavigate('Notificações')}>Ver todas</button></div>
      {demo
        ? <div className="notification-row"><strong>08:47</strong><div><b>Falha ao enviar notificação</b><span>Reprocessamento automático pendente</span></div></div>
        : overview.failed_notifications > 0
          ? <div className="notification-row"><strong>{overview.failed_notifications}</strong><div><b>{overview.failed_notifications === 1 ? 'Notificação com falha' : 'Notificações com falha'}</b><span>A entrega requer atenção operacional.</span></div></div>
          : <div className="activity-empty">Nenhuma notificação pendente.</div>}
    </div>
  </section>
}

function ApiNotice({ message, onRetry }) {
  return <div className="api-notice" role="status">
    <div className="api-notice-icon"><Icon name="alert" size={18} /></div>
    <div className="api-notice-copy"><strong>Modo demonstração</strong><span>{message}</span></div>
    <button type="button" onClick={onRetry}>Tentar novamente</button>
  </div>
}

function App() {
  const [activeNav, setActiveNav] = useState('Visão da operação')
  const [overview, setOverview] = useState(demoOverview)
  const [filter, setFilter] = useState('Todos')
  const [loading, setLoading] = useState(false)
  const [live, setLive] = useState(false)
  const [apiError, setApiError] = useState('')
  const [operatorToken, setOperatorToken] = useState(() => sessionStorage.getItem('market.operator.token') || '')
  const [session, setSession] = useState(null)
  const [authRequired, setAuthRequired] = useState(Boolean(supabase))
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authLoading, setAuthLoading] = useState(false)
  const [authError, setAuthError] = useState('')
  const [paymentStatus, setPaymentStatus] = useState('')
  const [paymentOffset, setPaymentOffset] = useState(0)
  const [paymentItems, setPaymentItems] = useState([])
  const [paymentTotal, setPaymentTotal] = useState(0)
  const [paymentsGeneratedAt, setPaymentsGeneratedAt] = useState(null)
  const [paymentsLoading, setPaymentsLoading] = useState(false)
  const [paymentsError, setPaymentsError] = useState('')
  const [debtStatus, setDebtStatus] = useState('')
  const [debtOffset, setDebtOffset] = useState(0)
  const [debtItems, setDebtItems] = useState([])
  const [debtTotal, setDebtTotal] = useState(0)
  const [debtAmountCents, setDebtAmountCents] = useState(0)
  const [debtsGeneratedAt, setDebtsGeneratedAt] = useState(null)
  const [debtsLoading, setDebtsLoading] = useState(false)
  const [debtsError, setDebtsError] = useState('')
  const fetchOverview = async (tokenOverride = session?.access_token || operatorToken) => {
    setLoading(true)
    try {
      const base = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? '/api' : 'http://127.0.0.1:8000')
      if (!import.meta.env.VITE_API_BASE_URL) {
        setApiError('A URL pública da API ainda não foi configurada neste ambiente.')
      }
      const token = tokenOverride.trim()
      const response = await fetch(`${base}/operator/overview?limit=20`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      if (response.status === 401 || response.status === 403) { setAuthRequired(true); setAuthError('Token inválido ou sem permissão para esta operação.'); setApiError('A sessão atual não tem permissão para consultar a operação.'); throw new Error('operator authentication required') }
      if (!response.ok) { setApiError(`A API respondeu com o status ${response.status}.`); throw new Error('API unavailable') }
      setOverview(await response.json())
      setLive(true)
      setApiError('')
    } catch (error) {
      setLive(false)
      if (error instanceof TypeError) setApiError('Não foi possível alcançar a API. Verifique a URL pública e o CORS.')
    } finally { setLoading(false) }
  }
  const fetchPayments = useCallback(async () => {
    setPaymentsLoading(true)
    setPaymentsError('')
    try {
      const base = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? '/api' : 'http://127.0.0.1:8000')
      const params = new URLSearchParams({ limit: '20', offset: String(paymentOffset) })
      if (paymentStatus) params.set('status', paymentStatus)
      const token = session?.access_token || operatorToken
      const response = await fetch(base + '/operator/payments?' + params.toString(), { headers: token ? { Authorization: 'Bearer ' + token } : {} })
      if (response.status === 401 || response.status === 403) {
        setAuthRequired(true)
        setAuthError('Token inválido ou sem permissão para consultar pagamentos.')
        throw new Error('A sessão atual não tem permissão para consultar pagamentos.')
      }
      if (!response.ok) throw new Error('A API respondeu com o status ' + response.status + '.')
      const page = await response.json()
      setPaymentItems(page.items)
      setPaymentTotal(page.total)
      setPaymentsGeneratedAt(page.generated_at)
    } catch (error) {
      setPaymentsError(error instanceof TypeError ? 'Não foi possível alcançar a API de pagamentos.' : error.message)
    } finally {
      setPaymentsLoading(false)
    }
  }, [operatorToken, paymentOffset, paymentStatus, session?.access_token])
  const fetchDebts = useCallback(async () => {
    setDebtsLoading(true)
    setDebtsError('')
    try {
      const base = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? '/api' : 'http://127.0.0.1:8000')
      const params = new URLSearchParams({ limit: '20', offset: String(debtOffset) })
      if (debtStatus) params.set('status', debtStatus)
      const token = session?.access_token || operatorToken
      const response = await fetch(base + '/operator/debts?' + params.toString(), { headers: token ? { Authorization: 'Bearer ' + token } : {} })
      if (response.status === 401 || response.status === 403) {
        setAuthRequired(true)
        setAuthError('Token inválido ou sem permissão para consultar dívidas.')
        throw new Error('A sessão atual não tem permissão para consultar dívidas.')
      }
      if (!response.ok) throw new Error('A API respondeu com o status ' + response.status + '.')
      const page = await response.json()
      setDebtItems(page.items)
      setDebtTotal(page.total)
      setDebtAmountCents(page.total_amount_cents)
      setDebtsGeneratedAt(page.generated_at)
    } catch (error) {
      setDebtsError(error instanceof TypeError ? 'Não foi possível alcançar a API de dívidas.' : error.message)
    } finally {
      setDebtsLoading(false)
    }
  }, [debtOffset, debtStatus, operatorToken, session?.access_token])
  const submitToken = (event) => { event.preventDefault(); const token = operatorToken.trim().replace(/^Bearer\s+/i, ''); if (!token) { setAuthError('Informe o token do operador.'); return }; setOperatorToken(token); sessionStorage.setItem('market.operator.token', token); setAuthError(''); setAuthRequired(false); fetchOverview(token) }
  const submitSupabaseLogin = async (event) => {
    event.preventDefault()
    if (!supabase) return
    setAuthLoading(true)
    setAuthError('')
    const { data, error } = await supabase.auth.signInWithPassword({ email: authEmail.trim(), password: authPassword })
    if (error) { setAuthError(error.message || 'Não foi possível entrar.'); setAuthLoading(false); return }
    setSession(data.session)
    setAuthRequired(false)
    setAuthPassword('')
    if (data.session) await fetchOverview(data.session.access_token)
    setAuthLoading(false)
  }
  const logout = async () => { if (supabase) await supabase.auth.signOut(); sessionStorage.removeItem('market.operator.token'); setOperatorToken(''); setSession(null); setAuthRequired(true); setLive(false) }
  useEffect(() => {
    if (!supabase) { fetchOverview(); return undefined }
    let mounted = true
    supabase.auth.getSession().then(({ data, error }) => {
      if (!mounted) return
      if (error) { setAuthError('Não foi possível recuperar a sessão.'); setAuthRequired(true); return }
      setSession(data.session)
      setAuthRequired(!data.session)
      if (data.session) fetchOverview(data.session.access_token)
    })
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
      setAuthRequired(!nextSession)
      if (nextSession) fetchOverview(nextSession.access_token)
    })
    return () => { mounted = false; listener.subscription.unsubscribe() }
  }, [])
  useEffect(() => {
    if (activeNav === 'Pagamentos') fetchPayments()
  }, [activeNav, fetchPayments])
  useEffect(() => {
    if (activeNav === 'Dívidas abertas') fetchDebts()
  }, [activeNav, fetchDebts])
  const updatedAtValue = activeNav === 'Pagamentos' && paymentsGeneratedAt ? paymentsGeneratedAt : activeNav === 'Dívidas abertas' && debtsGeneratedAt ? debtsGeneratedAt : overview.generated_at
  const updatedAt = useMemo(() => new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(updatedAtValue)), [updatedAtValue])
  const recentEvents = overview.recent_events || []
  const content = activeNav === 'Visão da operação'
    ? <><StatusBand overview={overview} /><div className="content-grid"><EventTimeline events={recentEvents} filter={filter} onFilter={setFilter} /><ActivityPanel overview={overview} demo={!live} onNavigate={setActiveNav} /></div></>
    : activeNav === 'Acessos'
      ? <AccessesPanel events={recentEvents} />
      : activeNav === 'Pagamentos'
        ? <PaymentsPanel items={paymentItems} total={paymentTotal} limit={20} offset={paymentOffset} status={paymentStatus} loading={paymentsLoading} error={paymentsError} onStatusChange={(value) => { setPaymentStatus(value); setPaymentOffset(0); setPaymentItems([]) }} onPageChange={(value) => { setPaymentOffset(value); setPaymentItems([]) }} onRetry={fetchPayments} />
        : activeNav === 'Dívidas abertas'
          ? <DebtsPanel items={debtItems} total={debtTotal} totalAmountCents={debtAmountCents} limit={20} offset={debtOffset} status={debtStatus} loading={debtsLoading} error={debtsError} onStatusChange={(value) => { setDebtStatus(value); setDebtOffset(0); setDebtItems([]); setDebtTotal(0); setDebtAmountCents(0) }} onPageChange={(value) => { setDebtOffset(value); setDebtItems([]) }} onRetry={fetchDebts} />
          : activeNav === 'Auditoria'
            ? <EventTimeline events={recentEvents} filter={filter} onFilter={setFilter} />
            : <ComingSoonPanel section={activeNav} />
  return <div className="app-shell"><aside className="sidebar"><div className="brand-mark" aria-label="Mercadinho Central"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M7 17h26l-3-8H10l-3 8Z" /><path d="M9 17v15h22V17" /><path d="M15 32V22h10v10" /><path d="M7 17h26" /></svg></div><nav>{navItems.map((item) => <button key={item.label} type="button" className={activeNav === item.label ? 'active' : ''} onClick={() => setActiveNav(item.label)}><Icon name={item.icon} size={19} /><span>{item.label}</span></button>)}</nav><button className="audit-link" type="button" onClick={() => setActiveNav('Auditoria')}><Icon name="shield" size={19} /><span>Auditoria</span></button></aside><main className="main-content"><header className="topbar"><div><h1>{activeNav}</h1><p>Mercadinho Central <span className="topbar-dot">·</span> POC assistida</p></div><div className="updated"><span>Última atualização</span><strong>{updatedAt}</strong><button type="button" className={`refresh-button ${loading ? 'spinning' : ''}`} onClick={fetchOverview} aria-label="Atualizar dados"><Icon name="refresh" size={19} /></button><span className={`connection ${live ? 'live' : ''}`}><i />{live ? 'API conectada' : 'Modo demonstração'}</span>{(session || operatorToken) && <button className="logout-button" type="button" onClick={logout}>Sair</button>}</div></header>{apiError && <ApiNotice message={apiError} onRetry={fetchOverview} />}{content}<footer className="footer"><span><i className="footer-dot" /> Operação monitorada</span><span>Dados atualizados automaticamente</span></footer></main>{authRequired && <div className="auth-overlay">{supabase ? <form className="auth-dialog" onSubmit={submitSupabaseLogin}><div className="auth-icon"><Icon name="shield" size={25} /></div><h2>Acesso do operador</h2><p>Entre com sua conta de operador para consultar a operação da loja.</p><label htmlFor="auth-email">E-mail</label><input id="auth-email" type="email" required autoFocus value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} placeholder="operador@mercadinho.com" autoComplete="email" /><label htmlFor="auth-password">Senha</label><input id="auth-password" type="password" required value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder="Sua senha" autoComplete="current-password" />{authError && <span className="auth-error">{authError}</span>}<button className="auth-submit" type="submit" disabled={authLoading}>{authLoading ? 'Entrando…' : 'Entrar na operação'}</button><small>A sessão fica somente nesta sessão do navegador.</small></form> : <form className="auth-dialog" onSubmit={submitToken}><div className="auth-icon"><Icon name="shield" size={25} /></div><h2>Acesso do operador</h2><p>Informe o token de sessão para consultar a operação da loja.</p><label htmlFor="operator-token">Token do operador</label><input id="operator-token" type="password" autoFocus value={operatorToken} onChange={(event) => setOperatorToken(event.target.value)} placeholder="Token de sessão" autoComplete="current-password" />{authError && <span className="auth-error">{authError}</span>}<button className="auth-submit" type="submit">Entrar na operação</button><small>O token fica somente nesta sessão do navegador.</small></form>}</div>}</div>
}

createRoot(document.getElementById('root')).render(<App />)
