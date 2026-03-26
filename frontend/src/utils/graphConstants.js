// Graph visual constants — tuned for warm light theme

export const NODE_META = {
  SalesOrder:   { color: '#4267B8', bg: '#EBF0FB', label: 'Sales Order',   icon: '⬡', size: 10 },
  Delivery:     { color: '#2D7D52', bg: '#EAF4EE', label: 'Delivery',      icon: '⬡', size: 10 },
  BillingDoc:   { color: '#B86E1A', bg: '#FDF5E4', label: 'Billing Doc',   icon: '⬡', size: 10 },
  Payment:      { color: '#7B4BAD', bg: '#F2EDFB', label: 'Payment',       icon: '⬡', size: 9  },
  JournalEntry: { color: '#C0404A', bg: '#FAEAEA', label: 'Journal Entry', icon: '⬡', size: 8  },
  Customer:     { color: '#1E7D9B', bg: '#E8F4F8', label: 'Customer',      icon: '⬡', size: 14 },
  Product:      { color: '#4D8B7A', bg: '#EBF4F1', label: 'Product',       icon: '⬡', size: 11 },
  Plant:        { color: '#8B6B3D', bg: '#F5F0E8', label: 'Plant',         icon: '⬡', size: 12 },
};

export const FLOW_ORDER = [
  'SalesOrder', 'Delivery', 'BillingDoc', 'Payment', 'JournalEntry'
];

export const FLOW_TYPES = new Set(FLOW_ORDER);

export const SUGGESTED_QUERIES = [
  'Which products have the most billing documents?',
  'Trace flow of billing doc 90504248',
  'Orders delivered but never billed',
  'Total revenue collected',
  'How many cancelled billing documents?',
  'Sales orders with no delivery',
  'Which customer has the most orders?',
  'Average order value by customer',
];

export function getNodeMeta(type) {
  return NODE_META[type] || { color: '#8B8480', bg: '#F0EDE8', label: type, icon: '⬡', size: 8 };
}

export function getNodeColor(type) {
  return getNodeMeta(type).color;
}

export function getNodeSize(type) {
  return getNodeMeta(type).size;
}
