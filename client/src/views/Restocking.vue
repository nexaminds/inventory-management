<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <label class="budget-label" for="budget-slider">
          {{ t('restocking.budgetSlider') }}: <strong>{{ money(budget) }}</strong>
        </label>
        <input
          id="budget-slider"
          v-model.number="budget"
          class="budget-slider"
          type="range"
          min="0"
          :max="maxBudget"
          :step="BUDGET_STEP"
          :disabled="maxBudget === 0"
        />
        <div class="budget-scale">
          <span>{{ money(0) }}</span>
          <span>{{ money(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ money(budget) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.allocated') }}</div>
          <div class="stat-value">{{ money(allocatedTotal) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ money(remainingBudget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsToOrder') }}</div>
          <div class="stat-value">{{ recommendedItems.length }}</div>
        </div>
      </div>

      <div v-if="orderResult" class="notice success-notice">
        {{ t('restocking.orderPlaced', { orderNumber: orderResult.order_number, date: formatDate(orderResult.expected_delivery) }) }}
        <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="notice error-notice">
        {{ t('restocking.orderFailed') }}: {{ submitError }}
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="place-order-btn"
            type="button"
            :disabled="recommendedItems.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="suggestions.length === 0" class="empty-state">{{ t('restocking.noSuggestions') }}</div>
        <div v-else-if="recommendedItems.length === 0" class="empty-state">{{ t('restocking.noneAffordable') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.suggestedQty') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in recommendedItems" :key="row.item_sku">
                <td>
                  <strong>{{ row.item_name }}</strong>
                  <div class="sku">{{ row.item_sku }}</div>
                </td>
                <td>
                  <span :class="['badge', row.trend]">{{ t(`trends.${row.trend}`) }}</span>
                </td>
                <td>{{ row.suggestedQty }}</td>
                <td>
                  <strong>{{ row.quantity }}</strong>
                  <span v-if="row.quantity < row.suggestedQty" class="badge warning partial-badge">
                    {{ t('restocking.partial') }}
                  </span>
                </td>
                <td>{{ money(row.unit_cost, 2) }}</td>
                <td><strong>{{ money(row.lineTotal, 2) }}</strong></td>
                <td>{{ row.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const BUDGET_STEP = 100

const TREND_RANK = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const orderResult = ref(null)

    // Global filters intentionally not used: forecasts have no warehouse/category.

    const money = (amount, decimals = 0) =>
      formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)

    const formatDate = (dateString) => {
      // The API returns date-only strings ("2026-11-22"); new Date() would read them
      // as UTC midnight and show the previous day in US time zones, so parse as local.
      const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(dateString) ? `${dateString}T00:00:00` : dateString)
      if (isNaN(date.getTime())) return dateString
      return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
      })
    }

    // Suggested quantity = shortfall of current demand vs forecast (never negative).
    // Items with no shortfall are dropped. Order: increasing trend first, then the
    // biggest spend (gap x unit cost) first, so the budget goes to the most urgent,
    // highest-impact items.
    const suggestions = computed(() => {
      return forecasts.value
        .map(f => {
          const suggestedQty = Math.max(f.forecasted_demand - f.current_demand, 0)
          return { ...f, suggestedQty, fullCost: suggestedQty * f.unit_cost }
        })
        .filter(f => f.suggestedQty > 0)
        .sort((a, b) => {
          const rankDiff = (TREND_RANK[a.trend] ?? 3) - (TREND_RANK[b.trend] ?? 3)
          return rankDiff !== 0 ? rankDiff : b.fullCost - a.fullCost
        })
    })

    // Slider max: cost of buying every suggested quantity, rounded up to next $100.
    const maxBudget = computed(() => {
      const total = suggestions.value.reduce((sum, s) => sum + s.fullCost, 0)
      return Math.ceil(total / BUDGET_STEP - 1e-9) * BUDGET_STEP
    })

    // Greedy allocation. Work in integer cents so float error can never push the
    // allocated total above the budget. A line that doesn't fully fit is reduced to
    // floor(remaining / unit_cost) units (skipped if 0), and we keep scanning so
    // cheaper items later in the order can still use leftover budget.
    const recommendedItems = computed(() => {
      let remainingCents = Math.round(budget.value * 100)
      const result = []
      for (const s of suggestions.value) {
        const unitCents = Math.round(s.unit_cost * 100)
        if (unitCents <= 0) continue
        const quantity = Math.min(s.suggestedQty, Math.floor(remainingCents / unitCents))
        if (quantity <= 0) continue
        remainingCents -= quantity * unitCents
        result.push({ ...s, quantity, lineTotal: (quantity * unitCents) / 100 })
      }
      return result
    })

    const allocatedTotal = computed(() =>
      recommendedItems.value.reduce((sum, r) => sum + Math.round(r.lineTotal * 100), 0) / 100
    )
    const remainingBudget = computed(() => Math.max(budget.value - allocatedTotal.value, 0))

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        // Default to 50% of max, rounded to the slider step
        budget.value = Math.round(maxBudget.value * 0.5 / BUDGET_STEP) * BUDGET_STEP
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendedItems.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      orderResult.value = null
      try {
        orderResult.value = await api.createRestockingOrder({
          budget: budget.value,
          items: recommendedItems.value.map(r => ({
            item_sku: r.item_sku,
            item_name: r.item_name,
            quantity: r.quantity,
            unit_cost: r.unit_cost,
            lead_time_days: r.lead_time_days
          }))
        })
      } catch (err) {
        submitError.value = err.response?.data?.detail || err.message
      } finally {
        submitting.value = false
      }
    }

    // A confirmation or error belongs to the budget it was placed with; clear it once
    // the user moves the slider so it can't be mistaken for the new selection.
    watch(budget, () => {
      orderResult.value = null
      submitError.value = null
    })

    onMounted(loadForecasts)

    return {
      t,
      BUDGET_STEP,
      loading,
      error,
      budget,
      maxBudget,
      suggestions,
      recommendedItems,
      allocatedTotal,
      remainingBudget,
      submitting,
      submitError,
      orderResult,
      money,
      formatDate,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-label {
  display: block;
  font-size: 0.875rem;
  color: #64748b;
  margin-bottom: 0.75rem;
}

.budget-label strong {
  color: #0f172a;
}

.budget-slider {
  width: 100%;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 0.25rem;
}

.sku {
  font-size: 0.75rem;
  color: #64748b;
}

.partial-badge {
  margin-left: 0.5rem;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.notice {
  padding: 0.875rem 1rem;
  border-radius: 8px;
  margin-bottom: 1.5rem;
  font-size: 0.875rem;
}

.notice a {
  margin-left: 0.5rem;
  font-weight: 600;
  color: inherit;
  text-decoration: underline;
}

.success-notice {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.error-notice {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}
</style>
