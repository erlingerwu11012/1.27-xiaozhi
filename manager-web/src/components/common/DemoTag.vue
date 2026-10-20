<template>
  <span v-if="show" class="xn-tag xn-tag--demo" :title="$t('xn.mock.desc')">{{ text || $t('xn.mock.badge') }}</span>
</template>

<script>
/* “演示数据”标记：只在 mock 模式出现，用于余额、订单、支付结果等容易被误认成真实数据的位置。 */
import { isMockMode } from '@/mock/config';

export default {
  name: 'DemoTag',
  props: { text: { type: String, default: '' } },
  computed: { show: () => isMockMode() },
};
</script>
