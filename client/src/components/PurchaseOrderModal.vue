<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen && backlogItem" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">{{ mode === 'view' ? 'Purchase Order' : 'Create Purchase Order' }}</h3>
            <button class="close-button" @click="close" aria-label="Close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <div class="item-context">
              <h4 class="item-name">{{ translateProductName(backlogItem.item_name) }}</h4>
              <div class="item-sku">SKU: {{ backlogItem.item_sku }}</div>
              <div class="item-shortage">Shortage: {{ shortage }} units</div>
            </div>

            <!-- Create mode -->
            <form v-if="mode === 'create'" id="po-form" class="po-form" @submit.prevent="submit">
              <div class="form-field">
                <label for="po-supplier">Supplier name</label>
                <input id="po-supplier" v-model="form.supplier_name" type="text" required />
              </div>

              <div class="form-row">
                <div class="form-field">
                  <label for="po-quantity">Quantity</label>
                  <input id="po-quantity" v-model.number="form.quantity" type="number" min="1" step="1" required />
                </div>
                <div class="form-field">
                  <label for="po-cost">Unit cost ($)</label>
                  <input id="po-cost" v-model.number="form.unit_cost" type="number" min="0.01" step="0.01" required />
                </div>
              </div>

              <div class="form-field">
                <label for="po-date">Expected delivery date</label>
                <input id="po-date" v-model="form.expected_delivery_date" type="date" :min="today" required />
              </div>

              <div class="form-field">
                <label for="po-notes">Notes (optional)</label>
                <textarea id="po-notes" v-model="form.notes" rows="3"></textarea>
              </div>

              <div class="total-row">
                <span class="info-label">Total</span>
                <span class="total-value">{{ formatMoney(total) }}</span>
              </div>

              <div v-if="submitError" class="error-message" role="alert">{{ submitError }}</div>
            </form>

            <!-- View mode -->
            <div v-else>
              <div v-if="loading" class="state-message">Loading purchase order...</div>
              <div v-else-if="loadError" class="error-message" role="alert">{{ loadError }}</div>
              <div v-else-if="purchaseOrder" class="info-grid">
                <div class="info-item">
                  <div class="info-label">PO ID</div>
                  <div class="info-value mono">{{ purchaseOrder.id }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Status</div>
                  <div class="info-value"><span class="badge">{{ purchaseOrder.status }}</span></div>
                </div>
                <div class="info-item">
                  <div class="info-label">Supplier</div>
                  <div class="info-value">{{ purchaseOrder.supplier_name }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Quantity</div>
                  <div class="info-value">{{ purchaseOrder.quantity }} units</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Unit cost</div>
                  <div class="info-value">{{ formatMoney(purchaseOrder.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Total</div>
                  <div class="info-value">{{ formatMoney(purchaseOrder.quantity * purchaseOrder.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Expected delivery</div>
                  <div class="info-value">{{ formatDate(purchaseOrder.expected_delivery_date) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">Created</div>
                  <div class="info-value">{{ formatDate(purchaseOrder.created_date) }}</div>
                </div>
                <div class="info-item full">
                  <div class="info-label">Notes</div>
                  <div class="info-value">{{ purchaseOrder.notes || 'None' }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn-secondary" @click="close">
              {{ mode === 'view' ? 'Close' : 'Cancel' }}
            </button>
            <button
              v-if="mode === 'create'"
              type="submit"
              form="po-form"
              class="btn-primary"
              :disabled="!isValid || saving"
            >
              {{ saving ? 'Saving...' : 'Create PO' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const { translateProductName } = useI18n()

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  backlogItem: { type: Object, default: null },
  mode: { type: String, default: 'create' } // 'create' | 'view'
})

const emit = defineEmits(['close', 'po-created', 'po-exists'])

const form = ref({
  supplier_name: '',
  quantity: 1,
  unit_cost: null,
  expected_delivery_date: '',
  notes: ''
})
const saving = ref(false)
const submitError = ref(null)

const purchaseOrder = ref(null)
const loading = ref(false)
const loadError = ref(null)

// Local YYYY-MM-DD (not toISOString, which is UTC and can be off by a day);
// the server rejects past delivery dates, so block them in the picker too
const now = new Date()
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`

const shortage = computed(() => {
  if (!props.backlogItem) return 0
  return Math.max(0, props.backlogItem.quantity_needed - props.backlogItem.quantity_available)
})

const total = computed(() => (Number(form.value.quantity) || 0) * (Number(form.value.unit_cost) || 0))

const isValid = computed(() => {
  const f = form.value
  return (
    f.supplier_name.trim().length > 0 &&
    Number(f.quantity) > 0 &&
    Number(f.unit_cost) > 0 &&
    !!f.expected_delivery_date
  )
})

const resetForm = () => {
  form.value = {
    supplier_name: '',
    quantity: shortage.value > 0 ? shortage.value : 1,
    unit_cost: null,
    expected_delivery_date: '',
    notes: ''
  }
  saving.value = false
  submitError.value = null
}

const loadPurchaseOrder = async () => {
  loading.value = true
  loadError.value = null
  purchaseOrder.value = null
  const requestedId = props.backlogItem.id
  try {
    const po = await api.getPurchaseOrderByBacklogItem(requestedId)
    // Ignore stale responses if the modal moved to another item meanwhile
    if (props.backlogItem?.id === requestedId) purchaseOrder.value = po
  } catch (err) {
    console.error('Failed to load purchase order:', err)
    loadError.value = err.response?.data?.detail || 'Failed to load purchase order'
  } finally {
    loading.value = false
  }
}

// Reset/load each time the modal opens (or switches item/mode while open)
watch(
  () => [props.isOpen, props.backlogItem?.id, props.mode],
  () => {
    if (!props.isOpen || !props.backlogItem) return
    if (props.mode === 'view') {
      loadPurchaseOrder()
    } else {
      resetForm()
    }
  },
  { immediate: true }
)

const submit = async () => {
  if (!isValid.value || saving.value) return
  saving.value = true
  submitError.value = null
  try {
    const f = form.value
    const po = await api.createPurchaseOrder({
      backlog_item_id: props.backlogItem.id,
      supplier_name: f.supplier_name.trim(),
      quantity: Number(f.quantity),
      unit_cost: Number(f.unit_cost),
      expected_delivery_date: f.expected_delivery_date,
      notes: f.notes.trim() || null
    })
    emit('po-created', po)
  } catch (err) {
    // 409 means a PO already exists for this item (e.g. created from another tab),
    // so this row's "Create PO" state is stale; let the parent resync and show it
    if (err.response?.status === 409) {
      emit('po-exists', props.backlogItem.id)
      return
    }
    console.error('Failed to create purchase order:', err)
    const detail = err.response?.data?.detail
    submitError.value = typeof detail === 'string' ? detail : 'Failed to create purchase order'
  } finally {
    saving.value = false
  }
}

const close = () => emit('close')

const formatMoney = (value) => {
  const n = Number(value)
  if (isNaN(n)) return 'N/A'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  // Date-only strings (YYYY-MM-DD) parse as UTC and display a day early in
  // western timezones; anchor them to local midnight instead.
  const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(dateString)
  const date = new Date(isDateOnly ? `${dateString}T00:00:00` : dateString)
  if (isNaN(date.getTime())) return 'N/A'
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 1rem;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}

.item-context {
  padding-bottom: 1.25rem;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 1.5rem;
}

.item-name {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 0.375rem 0;
}

.item-sku {
  font-size: 0.875rem;
  color: #64748b;
  font-family: 'Monaco', 'Courier New', monospace;
}

.item-shortage {
  margin-top: 0.375rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #dc2626;
}

.po-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-field label,
.info-label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.form-field input,
.form-field textarea {
  padding: 0.625rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.938rem;
  font-family: inherit;
  color: #0f172a;
  background: white;
}

.form-field input:focus,
.form-field textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

.total-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.total-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.error-message {
  padding: 0.75rem 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.875rem;
}

.state-message {
  color: #64748b;
  font-size: 0.938rem;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.info-item.full {
  grid-column: 1 / -1;
}

.info-value {
  font-size: 0.938rem;
  color: #0f172a;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.info-value.mono {
  font-family: 'Monaco', 'Courier New', monospace;
  color: #2563eb;
}

.badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 6px;
  font-size: 0.813rem;
  font-weight: 600;
  background: #dbeafe;
  color: #1e40af;
}

.modal-footer {
  padding: 1.5rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary,
.btn-primary {
  padding: 0.625rem 1.25rem;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-secondary {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
}

.btn-secondary:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.btn-primary {
  background: #0f172a;
  border: 1px solid #0f172a;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal transition animations */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.2s ease;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95);
}
</style>
