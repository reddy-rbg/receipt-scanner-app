import { DARK_COLORS, useTheme } from '../../stores/themeStore';
import { useAuth, getUserToken, getGuestSessionId } from '../../stores/authStore';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useLocalSearchParams } from 'expo-router';
import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';
import { IconButton } from '../../components/IconButton';
import { showAlert } from '../../components/WebAlertHost';
import { SafeAreaView } from 'react-native-safe-area-context';
import { API } from '../../config/api';
import { useState, useEffect, useCallback, type ComponentProps } from 'react';
import {
  View, Text, Image, ScrollView, TouchableOpacity, StyleSheet,
  ActivityIndicator, Modal, FlatList, TextInput, RefreshControl,
  KeyboardAvoidingView, Platform, type ImageSourcePropType,
} from 'react-native';

const RECEIPTS_CACHE_KEY = 'receiptai:receipts-cache:v1';
const INVOICE_ITEM_PAGE_SIZE = 25;


const n = (v:any) => parseFloat(v)||0;
const hasVisibleMoney = (v:any) => v !== null && v !== undefined && v !== '' && n(v) > 0;

type Receipt = {
  id:number; store:string; date?:string; time?:string;
  address?:string; total?:number; total_savings?:number;
  items?:any[]; subtotal?:number; discount?:number;
  tax?:number; payment_method?:string; created_at?:string;
  transaction_number?:string; receipt_number?:string;
  invoice_number?:string; order_number?:string;
};

type ReceiptCategory = {
  key: string;
  label: string;
  icon: ComponentProps<typeof MaterialCommunityIcons>['name'];
  color: string;
};

type ReceiptItemVisual = {
  color: string;
  label: string;
} & (
  | { icon: ComponentProps<typeof MaterialCommunityIcons>['name']; image?: never }
  | { image: ImageSourcePropType; icon?: never }
);

const ITEM_PICTOGRAMS = {
  jalebi: require('../../assets/item-pictograms/jalebi.png'),
  tindora: require('../../assets/item-pictograms/tindora.png'),
  banana: require('../../assets/item-pictograms/banana.png'),
  garlic: require('../../assets/item-pictograms/garlic.png'),
  greenChilies: require('../../assets/item-pictograms/green-chilies.png'),
  avocado: require('../../assets/item-pictograms/avocado.png'),
  tomato: require('../../assets/item-pictograms/tomato.png'),
  curryLeaves: require('../../assets/item-pictograms/curry-leaves.png'),
  mint: require('../../assets/item-pictograms/mint.png'),
  jackfruit: require('../../assets/item-pictograms/jackfruit.png'),
  edamame: require('../../assets/item-pictograms/edamame.png'),
  broccoli: require('../../assets/item-pictograms/broccoli.png'),
  mixedVegetables: require('../../assets/item-pictograms/mixed-vegetables.png'),
  lemonGingerTea: require('../../assets/item-pictograms/lemon-ginger-tea.png'),
  broth: require('../../assets/item-pictograms/broth.png'),
  rice: require('../../assets/item-pictograms/rice.png'),
  flour: require('../../assets/item-pictograms/flour.png'),
  lentils: require('../../assets/item-pictograms/lentils.png'),
  dairy: require('../../assets/item-pictograms/dairy.png'),
  eggs: require('../../assets/item-pictograms/eggs.png'),
  bread: require('../../assets/item-pictograms/bread.png'),
  mixedFruit: require('../../assets/item-pictograms/mixed-fruit.png'),
  spices: require('../../assets/item-pictograms/spices.png'),
  seafood: require('../../assets/item-pictograms/seafood.png'),
  meat: require('../../assets/item-pictograms/meat.png'),
  cilantro: require('../../assets/item-pictograms/cilantro.png'),
  keema: require('../../assets/item-pictograms/keema.png'),
  greenOnion: require('../../assets/item-pictograms/green-onion.png'),
  cabbage: require('../../assets/item-pictograms/cabbage.png'),
  okra: require('../../assets/item-pictograms/okra.png'),
  squash: require('../../assets/item-pictograms/squash.png'),
  onion: require('../../assets/item-pictograms/onion.png'),
  eggplant: require('../../assets/item-pictograms/eggplant.png'),
  cucumber: require('../../assets/item-pictograms/cucumber.png'),
  ginger: require('../../assets/item-pictograms/ginger.png'),
  sweetPotato: require('../../assets/item-pictograms/sweet-potato.png'),
  genericProduct: require('../../assets/item-pictograms/generic-product.png'),
} satisfies Record<string, ImageSourcePropType>;

const FILTER_TABS = [
  { key:'all',   label:'All' },
  { key:'store', label:'Search' },
  { key:'category', label:'Category' },
  { key:'id',    label:'By ID' },
  { key:'month', label:'By Month' },
  { key:'year',  label:'By Year' },
  { key:'date',  label:'Date Range' },
  { key:'sort',  label:'Sort' },
];

const CATEGORIES: ReceiptCategory[] = [
  { key:'inventory',  label:'Wholesale Inventory', icon:'warehouse',              color:'#4678C8' },
  { key:'food',       label:'Food & Grocery',       icon:'basket',                 color:'#248A65' },
  { key:'restaurant', label:'Restaurants',          icon:'silverware-fork-knife',  color:'#CE556A' },
  { key:'coffee',     label:'Coffee & Cafe',        icon:'coffee-outline',         color:'#936248' },
  { key:'garden',     label:'Gardening & Hardware', icon:'sprout-outline',         color:'#568F4C' },
  { key:'medical',    label:'Hospital & Medical',   icon:'hospital-box-outline',   color:'#D45C72' },
  { key:'pharmacy',   label:'Pharmacy & Health',    icon:'pill',                   color:'#9862B7' },
  { key:'bank',       label:'Bank & Finance',       icon:'bank-outline',           color:'#5274BA' },
  { key:'fuel',       label:'Fuel & Auto',          icon:'gas-station-outline',    color:'#D97732' },
  { key:'smoke',      label:'Smoke Shop',           icon:'smoking',                color:'#70616D' },
  { key:'home',       label:'Home & Household',     icon:'home-heart',             color:'#7470B7' },
  { key:'shopping',   label:'Retail Shopping',      icon:'shopping-outline',       color:'#238A8B' },
  { key:'other',      label:'Other',                icon:'receipt-text-outline',   color:'#755FB3' },
];

function categoryByKey(key: string) {
  return CATEGORIES.find(category => category.key === key) || CATEGORIES[CATEGORIES.length - 1];
}

function getReceiptItemVisual(item: any, receiptCategory?: ReceiptCategory): ReceiptItemVisual {
  const text = [item?.name, item?.item, item?.description, item?.category]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  const normalizedText = text.replace(/[^a-z0-9]+/g, ' ').trim();
  const paddedText = ` ${normalizedText} `;
  const has = (...terms: string[]) => terms.some(term => {
    const normalizedTerm = term.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    return normalizedTerm.length > 0 && paddedText.includes(` ${normalizedTerm} `);
  });

  if (n(item?.price) < 0 || has('discount', 'coupon', 'savings')) {
    return { icon:'tag-outline', color:'#6F63B6', label:'Discount' };
  }
  if (has(
    'vape', 'vaping', 'nicotine', 'nixodine', 'e liquid', 'eliquid',
    'cigarette', 'cigarettes', 'cigar', 'cigars', 'tobacco', 'rolling paper',
    'disposable pod', 'replacement pod', 'detox flush'
  )) {
    return { icon:'smoking', color:'#70616D', label:'Smoke shop item' };
  }

  const guardedCategoryVisuals: Partial<Record<string, ReceiptItemVisual>> = {
    garden:   { icon:'sprout-outline', color:'#568F4C', label:'Garden or hardware item' },
    medical:  { icon:'medical-bag', color:'#D45C72', label:'Medical item' },
    pharmacy: { icon:'pill', color:'#9862B7', label:'Pharmacy item' },
    bank:     { icon:'receipt-text-outline', color:'#5274BA', label:'Financial line item' },
    fuel:     { icon:'gas-station-outline', color:'#D97732', label:'Fuel or auto item' },
    smoke:    { icon:'smoking', color:'#70616D', label:'Smoke shop item' },
    home:     { icon:'home-heart', color:'#7470B7', label:'Household item' },
  };
  const guardedCategoryVisual = guardedCategoryVisuals[receiptCategory?.key || ''];
  if (guardedCategoryVisual) return guardedCategoryVisual;
  if (has('jalebi', 'jilebi', 'jelebi', 'jilabi')) {
    return { image:ITEM_PICTOGRAMS.jalebi, color:'#D97822', label:'Jalebi' };
  }
  if (has('curry leaf', 'curry leaves', 'curry lvs', 'karivepaku')) {
    return { image:ITEM_PICTOGRAMS.curryLeaves, color:'#378C55', label:'Curry leaves' };
  }
  if (has('tindora', 'dondakaya', 'ivy gourd')) {
    return { image:ITEM_PICTOGRAMS.tindora, color:'#4F9559', label:'Tindora' };
  }
  if (has(
    'green chili', 'green chilli', 'chili green', 'chilli green',
    'chili long green', 'chilli long green', 'long green chili', 'long green chilli',
    'chili thai green', 'chilli thai green', 'thai green chili', 'thai green chilli',
    'hari mirch'
  )) {
    return { image:ITEM_PICTOGRAMS.greenChilies, color:'#4B923E', label:'Green chilies' };
  }
  if (has('banana', 'plantain', 'raw banana')) {
    return { image:ITEM_PICTOGRAMS.banana, color:'#C99724', label:'Banana' };
  }
  if (has('garlic naan', 'garlic nan')) {
    return { image:ITEM_PICTOGRAMS.bread, color:'#AF7540', label:'Garlic naan' };
  }
  if (has('garlic')) {
    return { image:ITEM_PICTOGRAMS.garlic, color:'#9A7D69', label:'Garlic' };
  }
  if (has('avocado')) {
    return { image:ITEM_PICTOGRAMS.avocado, color:'#5A873B', label:'Avocado' };
  }
  if (has('tomato')) {
    return { image:ITEM_PICTOGRAMS.tomato, color:'#CB4B45', label:'Tomato' };
  }
  if (has('green onion', 'green onions', 'american green onion', 'onion green', 'scallion', 'scallions', 'spring onion', 'spring onions')) {
    return { image:ITEM_PICTOGRAMS.greenOnion, color:'#4B923E', label:'Green onion' };
  }
  if (has('cabbage')) {
    return { image:ITEM_PICTOGRAMS.cabbage, color:'#5B963F', label:'Cabbage' };
  }
  if (has('okra', 'bhindi', 'lady finger', 'lady fingers')) {
    return { image:ITEM_PICTOGRAMS.okra, color:'#4F9559', label:'Okra' };
  }
  if (has('squash', 'gourd', 'chayote', 'dosakai', 'lauki', 'sorakaya', 'karela', 'turai', 'beerakaya', 'zucchini', 'pumpkin')) {
    return { image:ITEM_PICTOGRAMS.squash, color:'#6E9A42', label:'Squash or gourd' };
  }
  if (has('eggplant', 'brinjal')) {
    return { image:ITEM_PICTOGRAMS.eggplant, color:'#76508F', label:'Eggplant' };
  }
  if (has('cucumber')) {
    return { image:ITEM_PICTOGRAMS.cucumber, color:'#4D963F', label:'Cucumber' };
  }
  if (has('onion', 'onions')) {
    return { image:ITEM_PICTOGRAMS.onion, color:'#A55B72', label:'Onion' };
  }
  if (has('ginger', 'galanga', 'galangal')) {
    return { image:ITEM_PICTOGRAMS.ginger, color:'#B7874D', label:'Ginger' };
  }
  if (has('sweet potato', 'sweet potatoes', 'yam', 'yams')) {
    return { image:ITEM_PICTOGRAMS.sweetPotato, color:'#B96846', label:'Sweet potato' };
  }
  if (has('cilantro', 'coriander leaves', 'coriander leaf', 'fresh coriander')) {
    return { image:ITEM_PICTOGRAMS.cilantro, color:'#3F8F50', label:'Cilantro' };
  }
  if (has('mint leaves', 'mint leaf', 'pudina')) {
    return { image:ITEM_PICTOGRAMS.mint, color:'#378C55', label:'Mint leaves' };
  }
  if (has('jackfruit', 'jack fruit')) {
    return { image:ITEM_PICTOGRAMS.jackfruit, color:'#A8862F', label:'Jackfruit' };
  }
  if (has('edamame', 'be edamame', 'gv edamame')) {
    return { image:ITEM_PICTOGRAMS.edamame, color:'#4D963F', label:'Edamame' };
  }
  if (has('broccoli', 'brflor', 'broc flor')) {
    return { image:ITEM_PICTOGRAMS.broccoli, color:'#438F55', label:'Broccoli' };
  }
  if (has('mixed vegetable', 'mixed veg', 'mxdvg')) {
    return { image:ITEM_PICTOGRAMS.mixedVegetables, color:'#4F9559', label:'Mixed vegetables' };
  }
  if (has('lemon ginger', 'lem gng', 'ginger tea', 'irani chai')) {
    return { image:ITEM_PICTOGRAMS.lemonGingerTea, color:'#A46E35', label:'Tea' };
  }
  if (has('bone broth', 'bone brt', 'kf bone brt', 'broth')) {
    return { image:ITEM_PICTOGRAMS.broth, color:'#A8753C', label:'Broth' };
  }
  if (has('goat keema', 'mutton keema', 'lamb keema', 'goat kheema', 'mutton kheema', 'kheema', 'qeema', 'keema')) {
    return { image:ITEM_PICTOGRAMS.keema, color:'#A94F43', label:'Keema' };
  }
  if (has('almond milk', 'almondmilk')) {
    return { image:ITEM_PICTOGRAMS.dairy, color:'#4A83B3', label:'Dairy alternative' };
  }
  if (has('ground chicken', 'grd ckn', 'hl grd ckn')) {
    return { image:ITEM_PICTOGRAMS.meat, color:'#BC6752', label:'Ground chicken' };
  }
  if (has('asparagus', 'sweet pepper', 'sweet peppers', 'swt pep', 'mini swt pep')) {
    return { image:ITEM_PICTOGRAMS.mixedVegetables, color:'#4F9559', label:'Fresh vegetable' };
  }
  if (has('popcorn', 'ppcrn', 'pcrn')) {
    return { icon:'popcorn', color:'#C58C24', label:'Popcorn' };
  }
  if (has('methi leaves', 'mint leaves', 'pudina', 'basil', 'parsley', 'thyme', 'rosemary', 'bay leaf', 'fresh herb')) {
    return { image:ITEM_PICTOGRAMS.mint, color:'#378C55', label:'Fresh herbs' };
  }
  if (has('paprika', 'chili', 'chilli', 'pepper', 'masala', 'spice', 'turmeric', 'haldi', 'cinnamon', 'saffron', 'cardamom', 'elaichi', 'cumin', 'jeera', 'clove', 'mustard seed', 'fenugreek seed', 'hing', 'asafoetida', 'seasoning')) {
    return { image:ITEM_PICTOGRAMS.spices, color:'#D15D3F', label:'Spice' };
  }
  if (has('tuna', 'fish', 'salmon', 'tilapia', 'seafood', 'shrimp', 'prawn')) {
    return { image:ITEM_PICTOGRAMS.seafood, color:'#287FA5', label:'Seafood' };
  }
  if (has('corn')) {
    return { icon:'corn', color:'#C89124', label:'Corn' };
  }
  if (has('mushroom', 'mush')) {
    return { icon:'mushroom-outline', color:'#8B6B57', label:'Mushroom' };
  }
  if (has('carrot')) {
    return { icon:'carrot', color:'#DE7333', label:'Carrot' };
  }
  if (has('green bean', 'green beans', 'beans', 'lentil', 'lentils', 'dal', 'dhal', 'chana', 'rajma', 'moong', 'mung', 'toor', 'urad', 'masoor', 'garbanzo', 'chickpea', 'chickpeas', 'peas', 'pea')) {
    return { image:ITEM_PICTOGRAMS.lentils, color:'#4C9461', label:'Beans or pulses' };
  }
  if (has('orange', 'oranges', 'lemon', 'lemons', 'lime', 'limes', 'citrus')) {
    return { image:ITEM_PICTOGRAMS.mixedFruit, color:'#E68A28', label:'Citrus fruit' };
  }
  if (has('lettuce', 'spinach', 'palak', 'kale', 'cilantro', 'coriander', 'greens', 'methi')) {
    return { image:ITEM_PICTOGRAMS.mixedVegetables, color:'#438F55', label:'Leafy vegetable' };
  }
  if (has('tomato', 'potato', 'garlic', 'radish', 'beetroot', 'beet root', 'cauliflower', 'broccoli', 'tindora', 'dondakaya', 'arbi', 'plantain', 'raw banana', 'moringa', 'vegetable', 'veggie')) {
    return { image:ITEM_PICTOGRAMS.mixedVegetables, color:'#4F9559', label:'Fresh vegetable' };
  }
  if (has('chicken', 'turkey', 'breast', 'brst', 'beef', 'steak', 'pork', 'goat', 'mutton', 'lamb', 'meat', 'ground meat')) {
    return { image:ITEM_PICTOGRAMS.meat, color:'#BC6752', label:'Meat' };
  }
  if (has('rice')) {
    return { image:ITEM_PICTOGRAMS.rice, color:'#9B7546', label:'Rice' };
  }
  if (has('atta', 'flour', 'besan', 'maida', 'semolina', 'sooji', 'suji', 'rava')) {
    return { image:ITEM_PICTOGRAMS.flour, color:'#A47742', label:'Flour' };
  }
  if (has('noodle', 'noodles', 'ramen', 'vermicelli', 'sevai', 'pasta', 'macaroni', 'spaghetti', 'spag')) {
    return { icon:'noodles', color:'#B87932', label:'Noodles or pasta' };
  }
  if (has('oats', 'wheat', 'barley', 'millet', 'ragi', 'jowar', 'bajra', 'quinoa', 'poha', 'grain')) {
    return { image:ITEM_PICTOGRAMS.rice, color:'#A47B36', label:'Grain' };
  }
  if (has('bread', 'bun', 'naan', 'roti', 'tortilla')) {
    return { image:ITEM_PICTOGRAMS.bread, color:'#AF7540', label:'Bread' };
  }
  if (has('egg')) {
    return { image:ITEM_PICTOGRAMS.eggs, color:'#C49331', label:'Eggs' };
  }
  if (has('cheese', 'paneer')) {
    return { image:ITEM_PICTOGRAMS.dairy, color:'#C99A2D', label:'Cheese' };
  }
  if (has('peanut', 'groundnut', 'almond', 'cashew', 'pistachio', 'walnut', 'mixed nuts')) {
    return { icon:'peanut-outline', color:'#9B6A3B', label:'Nuts' };
  }
  if (has('ice cream', 'icecream')) {
    return { icon:'ice-cream', color:'#B05D91', label:'Ice cream' };
  }
  if (has('milk', 'yogurt', 'curd', 'dairy', 'sour cream', 'heavy cream', 'whipping cream', 'sr c')) {
    return { image:ITEM_PICTOGRAMS.dairy, color:'#4A83B3', label:'Dairy' };
  }
  if (has('ghee', 'cooking oil', 'olive oil', 'vegetable oil', 'sunflower oil', 'canola oil')) {
    return { icon:'oil', color:'#B8892F', label:'Cooking oil' };
  }
  if (has('pickle', 'chutney', 'sauce', 'paste', 'sambar', 'rasam', 'curry')) {
    return { icon:'bowl-mix-outline', color:'#B26743', label:'Sauce or prepared food' };
  }
  if (has('salt', 'sugar', 'jaggery')) {
    return { icon:'shaker-outline', color:'#8A7381', label:'Pantry staple' };
  }
  if (has('coffee', 'tea')) {
    return { icon:'coffee-outline', color:'#8D6048', label:'Coffee or tea' };
  }
  if (has('water')) {
    return { icon:'water-outline', color:'#3D8FC1', label:'Water' };
  }
  if (has('juice', 'soda', 'coke', 'pepsi', 'drink', 'beverage', 'bubly', 'sparkling water')) {
    return { icon:'bottle-soda-outline', color:'#5B78B8', label:'Drink' };
  }
  if (has('coconut', 'pineapple')) {
    return { icon:'fruit-pineapple', color:'#A87935', label:'Tropical fruit' };
  }
  if (has('watermelon', 'melon')) {
    return { icon:'fruit-watermelon', color:'#D35661', label:'Melon' };
  }
  if (has('apple', 'apples', 'banana', 'bananas', 'mango', 'mangoes', 'grape', 'grapes', 'guava', 'papaya', 'fruit', 'fruits', 'berry', 'berries', 'mangosteen')) {
    return { image:ITEM_PICTOGRAMS.mixedFruit, color:'#7E62AE', label:'Fruit' };
  }
  if (has('cookie', 'biscuit', 'cracker', 'chips', 'mixture', 'namkeen', 'snack')) {
    return { icon:'cookie-outline', color:'#A76B3E', label:'Snack' };
  }
  if (has('pizza')) {
    return { icon:'pizza', color:'#C7653E', label:'Pizza' };
  }
  if (has('burger', 'hamburger')) {
    return { icon:'hamburger', color:'#A96E39', label:'Burger' };
  }
  if (has('cake', 'cupcake', 'muffin', 'pastry')) {
    return { icon:'cupcake', color:'#B45D82', label:'Bakery item' };
  }
  if (has('candy', 'chocolate', 'sweet candy', 'mithai')) {
    return { icon:'candy-outline', color:'#C2597A', label:'Candy' };
  }
  if (has('frozen', 'ice bag')) {
    return { icon:'snowflake', color:'#4B8FB5', label:'Frozen item' };
  }
  if (has('soap', 'cleaner', 'detergent', 'bleach', 'spray')) {
    return { icon:'spray-bottle', color:'#3F8C91', label:'Household cleaner' };
  }
  if (has('medicine', 'tablet', 'capsule', 'vitamin', 'pharmacy')) {
    return { icon:'medical-bag', color:'#AA5F94', label:'Health item' };
  }
  if (has('shirt', 'shirts', 't shirt', 'tee', 'dress', 'jeans', 'pants', 'short', 'shorts', 'clothing', 'apparel', 'woven short')) {
    return { icon:'hanger', color:'#6D71AE', label:'Clothing' };
  }
  if (has('tool', 'hardware', 'screw', 'nail', 'hammer')) {
    return { icon:'hammer-screwdriver', color:'#6C7480', label:'Hardware' };
  }

  const categoryFallbacks: Record<string, ReceiptItemVisual> = {
    food:       { image:ITEM_PICTOGRAMS.genericProduct, color:'#248A65', label:'Unidentified grocery product' },
    restaurant: { image:ITEM_PICTOGRAMS.bread, color:'#CE556A', label:'Prepared food' },
    coffee:     { image:ITEM_PICTOGRAMS.lemonGingerTea, color:'#936248', label:'Cafe item' },
    garden:     { icon:'sprout-outline', color:'#568F4C', label:'Garden or hardware item' },
    medical:    { icon:'medical-bag', color:'#D45C72', label:'Medical item' },
    pharmacy:   { icon:'pill', color:'#9862B7', label:'Pharmacy item' },
    bank:       { icon:'receipt-text-outline', color:'#5274BA', label:'Financial line item' },
    fuel:       { icon:'gas-station-outline', color:'#D97732', label:'Fuel or auto item' },
    smoke:      { icon:'smoking', color:'#70616D', label:'Smoke shop item' },
    home:       { icon:'home-heart', color:'#7470B7', label:'Household item' },
    shopping:   { image:ITEM_PICTOGRAMS.genericProduct, color:'#238A8B', label:'Unidentified retail product' },
    inventory:  { image:ITEM_PICTOGRAMS.genericProduct, color:'#4678C8', label:'Unidentified inventory product' },
  };

  return categoryFallbacks[receiptCategory?.key || ''] || { image:ITEM_PICTOGRAMS.genericProduct, color:'#7668A9', label:'Unidentified product' };
}

function receiptSearchText(receipt: Receipt) {
  const itemText = (receipt.items || [])
    .map((item:any) => [item?.name, item?.item, item?.code].filter(Boolean).join(' '))
    .join(' ');

  return [
    receipt.store,
    receipt.address,
    receipt.payment_method,
    itemText,
  ].filter(Boolean).join(' ').toLowerCase();
}

function matchAny(text: string, words: string[]) {
  return words.some(word => text.includes(word));
}

function itemDetailLines(item: any) {
  const lines: string[] = [];
  const quantity = n(item?.quantity) || 1;
  const unit = String(item?.unit || 'each').trim();
  const unitPrice = n(item?.unit_price);
  const productSize = item?.product_size || item?.size;
  const quantityType = item?.quantity_type;
  const unitLabel = item?.unit_label;
  const source = item?.source;

  if (productSize) lines.push(`Size: ${productSize}`);

  if (unit && unit.toLowerCase() !== 'each') {
    const qtyText = quantity > 0 ? `${quantity} ${unit}` : unit;
    const priceText = unitPrice > 0 ? ` @ $${unitPrice.toFixed(2)}/${unit}` : '';
    lines.push(`${qtyText}${priceText}`);
  } else if (quantity > 1) {
    const priceText = unitPrice > 0 ? ` @ $${unitPrice.toFixed(2)} each` : '';
    lines.push(`${quantity} each${priceText}`);
  } else if (unitPrice > 0 && unitPrice !== n(item?.price)) {
    lines.push(`Unit price: $${unitPrice.toFixed(2)}`);
  }

  if (unitLabel && unitLabel !== 'each' && !lines.some(line => line.includes(unitLabel))) {
    lines.push(unitLabel);
  }
  if (quantityType && quantityType !== 'each') {
    lines.push(`Type: ${String(quantityType).replace(/_/g, ' ')}`);
  }
  if (source && source !== 'printed') {
    lines.push(`Source: ${source}`);
  }
  if (item?.explicit_quantity === true) {
    lines.push('Explicit quantity shown on receipt');
  }

  return lines;
}

function itemPageCount(items: any[] = []) {
  return Math.max(1, Math.ceil(items.length / INVOICE_ITEM_PAGE_SIZE));
}

function itemPageItems(items: any[] = [], page: number) {
  const start = page * INVOICE_ITEM_PAGE_SIZE;
  return items.slice(start, start + INVOICE_ITEM_PAGE_SIZE).map((item, index) => ({
    item,
    originalIndex: start + index,
  }));
}

const INDIAN_GROCERY_TERMS = [
  'india mart', 'bharath bazaar', 'bharat bazaar', 'nwa bharath', 'nwa bharat',
  'asian amigo', 'indian grocery', 'desi', 'methi', 'amla', 'okra', 'bhindi',
  'goat', 'mutton', 'lamb', 'keema', 'kheema', 'qeema', 'dal', 'dhal', 'atta',
  'rice', 'masala', 'paneer', 'ghee', 'curry', 'squash', 'chana', 'garbanzo',
  'brinjal', 'eggplant', 'cilantro', 'coriander', 'dahi', 'curd', 'naan',
];

function getReceiptCategory(receipt: Receipt): ReceiptCategory {
  const text = receiptSearchText(receipt);
  const store = String(receipt.store || '').toLowerCase();

  // Stable merchant overrides keep mixed-category stores predictable.
  if (matchAny(store, ['costco', "sam's club", 'sams club'])) return categoryByKey('inventory');
  if (matchAny(store, ['exxon', 'exon express', 'express pay'])) return categoryByKey('fuel');
  if (matchAny(store, ['royal smokes', 'royal smoke', 'smoke shop', 'tobacco', 'vape', 'vapor planet', 'central arkansas wholesale', 'cigar'])) return categoryByKey('smoke');
  if (matchAny(store, ['produce', 'grocery', 'bazaar', 'bazar'])) return categoryByKey('food');
  if (matchAny(store, ['india bazaar', 'india bazar', 'namaste indian', 'bharath bazaar', 'bharat bazaar'])) return categoryByKey('food');
  if (matchAny(store, ['kfc', 'kentucky fried chicken', 'mcdonald', 'subway', 'popeyes', 'chick-fil-a', 'chick fil a'])) return categoryByKey('restaurant');
  if (matchAny(store, ['coffee', 'cafe', 'café', 'starbucks', 'dunkin', 'scooter'])) return categoryByKey('coffee');
  if (matchAny(store, ['walmart', 'wal mart', 'wal*mart'])) return categoryByKey('shopping');
  if (matchAny(store, ['ross dress for less', 'ross stores'])) return categoryByKey('shopping');

  if (matchAny(text, ['smoke shop', 'tobacco', 'cigarette', 'cigar', 'vape', 'nicotine', 'e-liquid', 'eliquid'])) {
    return categoryByKey('smoke');
  }
  if (matchAny(text, ['wholesale', 'invoice', 'sold to', 'ship to', 'warehouse'])) {
    return categoryByKey('inventory');
  }
  if (matchAny(text, ['bank', 'atm', 'withdrawal', 'deposit', 'credit union', 'chase', 'wells fargo', 'bank of america', 'capital one', 'payment receipt'])) {
    return categoryByKey('bank');
  }
  if (matchAny(text, ['hospital', 'clinic', 'medical center', 'urgent care', 'doctor', 'dental', 'dentist', 'labcorp', 'quest diagnostics', 'patient'])) {
    return categoryByKey('medical');
  }
  if (matchAny(text, ['cvs', 'walgreens', 'pharmacy', 'rx ', 'medicine', 'vitamin', 'health'])) {
    return categoryByKey('pharmacy');
  }
  if (matchAny(text, ['lowe', 'home depot', 'tractor supply', 'garden', 'mulch', 'soil', 'plant', 'rose', 'fertilizer', 'hardware', 'paint', 'lumber'])) {
    return categoryByKey('garden');
  }
  if (matchAny(text, ['restaurant', 'pizza', 'burger', 'taco', 'kfc', 'mcdonald', 'subway', 'doordash', 'uber eats', 'grubhub'])) {
    return categoryByKey('restaurant');
  }
  if (matchAny(text, ['walmart', 'wal mart', 'wal*mart', 'kroger', 'aldi', 'costco', 'sam club', 'target grocery', 'supermarket', 'market', 'grocery', 'food', 'seafood', 'milk', 'bread', 'egg', ...INDIAN_GROCERY_TERMS])) {
    return categoryByKey('food');
  }
  if (matchAny(text, ['shell', 'exxon', 'chevron', 'bp ', 'circle k', 'speedway', 'gas', 'fuel', 'auto', 'oil change', 'tire'])) {
    return categoryByKey('fuel');
  }
  if (matchAny(text, ['ikea', 'bed bath', 'household', 'cleaner', 'detergent', 'furniture', 'kitchen'])) {
    return categoryByKey('home');
  }
  if (matchAny(text, ['amazon', 'best buy', 'tj maxx', 'marshalls', 'mall', 'clothing', 'shoes', 'apparel', 'electronics'])) {
    return categoryByKey('shopping');
  }

  return categoryByKey('other');
}

const MONTHS = [
  {label:'January',val:'01'},{label:'February',val:'02'},{label:'March',val:'03'},
  {label:'April',val:'04'},{label:'May',val:'05'},{label:'June',val:'06'},
  {label:'July',val:'07'},{label:'August',val:'08'},{label:'September',val:'09'},
  {label:'October',val:'10'},{label:'November',val:'11'},{label:'December',val:'12'},
];

const YEARS = ['2026','2025','2024','2023'];

const SORTS = [
  {label:'Newest first',val:'newest'},
  {label:'Oldest first',val:'oldest'},
  {label:'Highest total',val:'highest'},
  {label:'Lowest total',val:'lowest'},
  {label:'Store AZ',val:'store'},
  {label:'Most savings',val:'savings'},
];

export default function ReceiptsScreen() {
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const { user } = useAuth(); // reactive theme updates
  const params = useLocalSearchParams<{ receiptId?: string | string[] }>();
  const receiptIdParam = Array.isArray(params.receiptId) ? params.receiptId[0] : params.receiptId;
  const [all, setAll]         = useState<Receipt[]>([]);
  const [shown, setShown]     = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab]   = useState('all');
  const [filterInfo, setFilterInfo] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Filter inputs
  const [storeQ,  setStoreQ]  = useState('');
  const [idQ,     setIdQ]     = useState('');
  const [month,   setMonth]   = useState('01');
  const [monthY,  setMonthY]  = useState('2026');
  const [year,    setYear]    = useState('2026');
  const [fromD,   setFromD]   = useState('');
  const [toD,     setToD]     = useState('');
  const [sortVal, setSortVal] = useState('newest');
  const [category, setCategory] = useState('food');

  // Modal
  const [selected,    setSelected]    = useState<Receipt|null>(null);
  const [deleteMode,  setDeleteMode]  = useState(false);
  const [deleted,     setDeleted]     = useState(false);
  const [editingItem, setEditingItem] = useState<{ index:number; item:any } | null>(null);
  const [editName, setEditName] = useState('');
  const [editPrice, setEditPrice] = useState('');
  const [editQty, setEditQty] = useState('');
  const [editSaving, setEditSaving] = useState(false);
  const [detailItemPage, setDetailItemPage] = useState(0);

  useEffect(() => { load(); }, [user?.id, user?.guest_session_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setDetailItemPage(0); }, [selected?.id]);

  useEffect(() => {
    if (!receiptIdParam || !all.length) return;
    const receipt = all.find(r => String(r.id) === String(receiptIdParam));
    if (!receipt) return;
    setSelected(receipt);
    setShown([receipt]);
    setFilterInfo(`Receipt #${receipt.id}`);
    setActiveTab('id');
    setDeleted(false);
    setDeleteMode(false);
  }, [receiptIdParam, all]);

  useEffect(() => {
    if (activeTab !== 'store') return;
    const q = storeQ.trim().toLowerCase();
    if (!q) {
      setShown(applySort(all, 'newest'));
      setFilterInfo('');
      return;
    }
    const r = all.filter(x =>
      receiptSearchText(x).includes(q) ||
      String(x.id).includes(q) ||
      getReceiptCategory(x).label.toLowerCase().includes(q)
    );
    showResults(r, `Search: "${storeQ.trim()}"`);
  }, [storeQ, activeTab, all]); // eslint-disable-line react-hooks/exhaustive-deps

  async function load() {
    try {
      if (!user) {
        setAll([]);
        setShown([]);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      if (!refreshing && all.length === 0) {
        try {
          const cached = await AsyncStorage.getItem(`${RECEIPTS_CACHE_KEY}:${user.id}`);
          const cachedReceipts = cached ? JSON.parse(cached) : [];
          if (Array.isArray(cachedReceipts) && cachedReceipts.length) {
            setAll(cachedReceipts);
            setShown(applySort(cachedReceipts, 'newest'));
            setLoading(false);
          }
        } catch {}
      }

      const guestId = getGuestSessionId();
      const isGuestMode = !!guestId || user?.isGuest || user?.is_guest || user?.token === 'guest';
      const url = isGuestMode
        ? `${API}/guest/receipts?session_id=${encodeURIComponent(guestId || user?.id || 'guest')}`
        : `${API}/receipts`;
      const headers:any = {};
      const token = getUserToken();
      if (!isGuestMode && token) headers['Authorization'] = `Bearer ${token}`;
      const res  = await fetch(url, { headers });
      const data = await res.json();
      const recs = data.receipts || [];
      setAll(recs);
      setShown(applySort(recs, 'newest'));
      await AsyncStorage.setItem(`${RECEIPTS_CACHE_KEY}:${user.id}`, JSON.stringify(recs));
      setFilterInfo('');
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }

  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // FILTER FUNCTIONS
  function applySort(recs: Receipt[], s: string) {
    const r = [...recs];
    switch (s) {
      case 'newest':  r.sort((a,b) => new Date(b.created_at||0).getTime() - new Date(a.created_at||0).getTime()); break;
      case 'oldest':  r.sort((a,b) => new Date(a.created_at||0).getTime() - new Date(b.created_at||0).getTime()); break;
      case 'highest': r.sort((a,b) => (b.total||0) - (a.total||0)); break;
      case 'lowest':  r.sort((a,b) => (a.total||0) - (b.total||0)); break;
      case 'store':   r.sort((a,b) => (a.store||'').localeCompare(b.store||'')); break;
      case 'savings': r.sort((a,b) => (b.total_savings||0) - (a.total_savings||0)); break;
    }
    return r;
  }

  function showResults(recs: Receipt[], label: string) {
    const sorted = applySort(recs, 'newest');
    setShown(sorted);
    setFilterInfo(label);
  }

  function filterByStore() {
    if (!storeQ.trim()) { load(); return; }
    const q = storeQ.trim().toLowerCase();
    const r = all.filter(x => receiptSearchText(x).includes(q) || String(x.id).includes(q) || getReceiptCategory(x).label.toLowerCase().includes(q));
    showResults(r, `Search: "${storeQ.trim()}"`);
  }

  function filterByCategory(value = category) {
    const selectedCategory = CATEGORIES.find(c => c.key === value) || CATEGORIES[CATEGORIES.length - 1];
    const r = all.filter(x => getReceiptCategory(x).key === selectedCategory.key);
    showResults(r, selectedCategory.label);
  }

  function filterById() {
    const id = parseInt(idQ.trim());
    if (!id) { load(); return; }
    const r = all.filter(x => x.id === id);
    showResults(r, `Receipt #${id}`);
  }

  function filterByMonth() {
    const r = all.filter(x => {
      if (!x.created_at) return false;
      const d = new Date(x.created_at);
      return String(d.getMonth()+1).padStart(2,'0') === month && String(d.getFullYear()) === monthY;
    });
    const mName = MONTHS.find(m => m.val === month)?.label || month;
    showResults(r, `${mName} ${monthY}`);
  }

  function filterByYear() {
    const r = all.filter(x => x.created_at && String(new Date(x.created_at).getFullYear()) === year);
    showResults(r, `Year ${year}`);
  }

  async function filterByDateRange() {
    if (!fromD || !toD) return;
    try {
      const guestId = getGuestSessionId();
      const token = getUserToken();
      const params = new URLSearchParams({ from_date: fromD, to_date: `${toD}T23:59:59` });
      if (guestId) params.set('session_id', guestId);
      const headers:any = {};
      if (!guestId && token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`${API}/receipts/date?${params.toString()}`, { headers });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not filter receipts.');
      showResults(data.receipts || [], `${fromD}  ${toD}`);
    } catch (e:any) {
      showAlert('Could not filter receipts', e.message || 'Please try again.');
    }
  }

  function doSort() {
    const sorted = applySort(all, sortVal);
    const label  = SORTS.find(s => s.val === sortVal)?.label || sortVal;
    setShown(sorted);
    setFilterInfo(`Sorted: ${label}`);
  }

  function applyFilter() {
    switch (activeTab) {
      case 'store': filterByStore(); break;
      case 'category': filterByCategory(); break;
      case 'id':    filterById();    break;
      case 'month': filterByMonth(); break;
      case 'year':  filterByYear();  break;
      case 'date':  filterByDateRange(); break;
      case 'sort':  doSort();        break;
      default:      load();
    }
  }

  async function deleteReceipt() {
    if (!selected) return;
    try {
      const guestId = getGuestSessionId();
      const token = getUserToken();
      const suffix = guestId ? `?session_id=${encodeURIComponent(guestId)}` : '';
      const headers:any = {};
      if (!guestId && token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(`${API}/receipts/${selected.id}${suffix}`, { method:'DELETE', headers });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not delete receipt.');
      setDeleted(true);
      setAll(prev => prev.filter(r => r.id !== selected.id));
      setShown(prev => prev.filter(r => r.id !== selected.id));
      setTimeout(() => { setSelected(null); setDeleted(false); setDeleteMode(false); }, 1600);
    } catch (e:any) {
      showAlert('Could not delete receipt', e.message || 'Please try again.');
    }
  }

  function startEditItem(index: number, item: any) {
    setEditingItem({ index, item });
    setEditName(item.name || item.item || '');
    setEditPrice(item.price != null ? String(item.price) : '');
    setEditQty(item.quantity != null ? String(item.quantity) : '1');
  }

  async function saveEditedItem() {
    if (!selected || !editingItem) return;
    if (!editName.trim()) {
      showAlert('Item name required', 'Please enter an item name.');
      return;
    }

    setEditSaving(true);
    try {
      const guestId = getGuestSessionId();
      const isGuestMode = !!guestId || user?.isGuest || user?.is_guest || user?.token === 'guest';
      const token = getUserToken();
      const headers:any = { 'Content-Type':'application/json' };
      if (!isGuestMode && token) headers.Authorization = `Bearer ${token}`;

      const res = await fetch(`${API}/receipts/${selected.id}/items/${editingItem.index}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({
          name: editName.trim(),
          price: n(editPrice),
          quantity: n(editQty) || 1,
          session_id: isGuestMode ? (guestId || user?.id) : undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not save item correction.');

      const updatedReceipt = data.receipt || selected;
      setSelected(updatedReceipt);
      setAll(prev => prev.map(r => r.id === updatedReceipt.id ? updatedReceipt : r));
      setShown(prev => prev.map(r => r.id === updatedReceipt.id ? updatedReceipt : r));
      setEditingItem(null);
      showAlert('Saved', 'Item correction saved. Price Memory will use the corrected item.');
    } catch (e:any) {
      showAlert('Could not save', e.message || 'Please try again.');
    } finally {
      setEditSaving(false);
    }
  }

  // FILTER PANEL CONTENT
  function renderFilterPanel() {
    switch (activeTab) {
      case 'store':
        return (
          <View style={s.searchHintBox}>
            <Text style={s.filterHint}>Results update while you type. Search store names, item names, categories, or receipt IDs.</Text>
          </View>
        );
      case 'category':
        return (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6,paddingBottom:8}}>
              {CATEGORIES.map(cat => (
                <TouchableOpacity
                  key={cat.key}
                  style={[s.selectChip, category===cat.key && s.selectChipActive]}
                  onPress={() => {
                    setCategory(cat.key);
                    filterByCategory(cat.key);
                  }}
                  activeOpacity={0.8}
                >
                  <Text style={[s.selectChipTxt, category===cat.key && s.selectChipTxtActive]}>{cat.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <Text style={s.filterHint}>Categories are detected from store names and scanned receipt items.</Text>
          </View>
        );
      case 'id':
        return (
          <View style={s.filterRow}>
            <TextInput style={s.filterInput} placeholder="Enter receipt ID..." placeholderTextColor={C.text3} value={idQ} onChangeText={setIdQ} onSubmitEditing={applyFilter} keyboardType="numeric" returnKeyType="search" autoCorrect={false}/>
            <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Find</Text></TouchableOpacity>
          </View>
        );
      case 'month':
        return (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6,paddingBottom:8}}>
              {MONTHS.map(m => (
                <TouchableOpacity key={m.val} style={[s.selectChip, month===m.val && s.selectChipActive]} onPress={() => setMonth(m.val)}>
                  <Text style={[s.selectChipTxt, month===m.val && s.selectChipTxtActive]}>{m.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <View style={s.filterRow}>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6}}>
                {YEARS.map(y => (
                  <TouchableOpacity key={y} style={[s.selectChip, monthY===y && s.selectChipActive]} onPress={() => setMonthY(y)}>
                    <Text style={[s.selectChipTxt, monthY===y && s.selectChipTxtActive]}>{y}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Filter</Text></TouchableOpacity>
            </View>
          </View>
        );
      case 'year':
        return (
          <View style={s.filterRow}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6}}>
              {YEARS.map(y => (
                <TouchableOpacity key={y} style={[s.selectChip, year===y && s.selectChipActive]} onPress={() => setYear(y)}>
                  <Text style={[s.selectChipTxt, year===y && s.selectChipTxtActive]}>{y}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Filter</Text></TouchableOpacity>
          </View>
        );
      case 'date':
        return (
          <View>
            <View style={s.filterRow}>
              <Text style={s.filterLabel}>From</Text>
              <TextInput style={s.filterInput} placeholder="YYYY-MM-DD" placeholderTextColor={C.text3} value={fromD} onChangeText={setFromD} autoCorrect={false}/>
            </View>
            <View style={s.filterRow}>
              <Text style={s.filterLabel}>To</Text>
              <TextInput style={s.filterInput} placeholder="YYYY-MM-DD" placeholderTextColor={C.text3} value={toD} onChangeText={setToD} autoCorrect={false}/>
              <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Filter</Text></TouchableOpacity>
            </View>
          </View>
        );
      case 'sort':
        return (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6,paddingBottom:8}}>
              {SORTS.map(so => (
                <TouchableOpacity key={so.val} style={[s.selectChip, sortVal===so.val && s.selectChipActive]} onPress={() => setSortVal(so.val)}>
                  <Text style={[s.selectChipTxt, sortVal===so.val && s.selectChipTxtActive]}>{so.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity style={[s.filterBtn,{alignSelf:'flex-start'}]} onPress={applyFilter}><Text style={s.filterBtnTxt}>Apply Sort</Text></TouchableOpacity>
          </View>
        );
      default:
        return null;
    }
  }

  return (
    <KeyboardAvoidingView
      style={s.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={0}
    >

      {/*  TOP SECTION (fixed)  */}
      <View style={s.top}>
        <View style={s.brandBar}>
          <View style={s.brandLeft}>
            <View style={s.miniPrismLogo}><View style={s.miniPrismViolet} /><View style={s.miniPrismMint} /></View>
            <Text style={s.brandName}>ReceiptAI</Text>
          </View>
          <View style={s.brandAction}><Ionicons name="search-outline" size={17} color={C.text2} /></View>
        </View>
        <View style={s.hero}>
          <Text style={s.heroKicker}>Everything in one glance</Text>
          <Text style={s.heroTitle}>Your receipts</Text>
          <Text style={s.heroSub}>A clear, searchable record of every purchase you save.</Text>
        </View>

        <View style={s.searchToolsRow}>
          <View style={s.searchBox}>
            <Ionicons name="search-outline" size={17} color={C.text3} />
            <TextInput
              style={s.searchInput}
              placeholder="Search store, item, or receipt"
              placeholderTextColor={C.text3}
              value={storeQ}
              onChangeText={(text) => {
                if (activeTab !== 'store') setActiveTab('store');
                setStoreQ(text);
              }}
              returnKeyType="search"
              autoCorrect={false}
              blurOnSubmit={false}
            />
            {storeQ ? (
              <TouchableOpacity
                style={s.searchClear}
                onPress={() => {
                  setStoreQ('');
                  setActiveTab('all');
                  setShown(applySort(all, 'newest'));
                  setFilterInfo('');
                }}
              >
                <Ionicons name="close" size={16} color={C.accent} />
              </TouchableOpacity>
            ) : null}
          </View>
          <TouchableOpacity
            style={[s.filterToggle, filtersOpen && s.filterToggleActive]}
            onPress={() => setFiltersOpen(open => !open)}
            activeOpacity={0.82}
            accessibilityRole="button"
            accessibilityLabel={filtersOpen ? 'Close receipt filters' : 'Open receipt filters'}
          >
            <Ionicons name="options-outline" size={18} color={filtersOpen || filterInfo ? C.accent : C.text2} />
            <Text style={[s.filterToggleTxt, (filtersOpen || filterInfo) && s.filterToggleTxtActive]}>Filters</Text>
            {filterInfo ? <View style={s.filterActiveDot} /> : null}
          </TouchableOpacity>
        </View>

        {filtersOpen ? (
          <View style={s.filterDrawer}>
            <Text style={s.filterDrawerKicker}>Refine receipts</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.tabsRow} keyboardShouldPersistTaps="handled">
              {FILTER_TABS.map(tab => (
                <TouchableOpacity
                  key={tab.key}
                  style={[s.tab, activeTab===tab.key && s.tabActive]}
                  onPress={() => {
                    setActiveTab(tab.key);
                    if (tab.key === 'all') {
                      setStoreQ('');
                      setShown(applySort(all, 'newest'));
                      setFilterInfo('');
                    }
                  }}
                >
                  <Text style={[s.tabTxt, activeTab===tab.key && s.tabTxtActive]}>{tab.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>

            <View style={s.filterPanel}>
              {renderFilterPanel()}
            </View>
          </View>
        ) : null}

        <View style={s.receiptSummary}>
          <Text style={s.receiptSummaryLabel}>{filterInfo || 'Saved receipts'}</Text>
          <Text style={s.receiptSummaryTotal}>${shown.reduce((sum, receipt) => sum + n(receipt.total), 0).toFixed(2)}</Text>
        </View>

        {/* Results info */}
        {filterInfo !== '' && (
          <View style={s.infoRow}>
            <Text style={s.infoTxt}><Text style={{color:C.text,fontWeight:'600'}}>{shown.length}</Text> receipt{shown.length!==1?'s':''}  {filterInfo}</Text>
            <TouchableOpacity onPress={load}><Text style={s.clearTxt}>Clear</Text></TouchableOpacity>
          </View>
        )}

        <Text style={s.countLbl}>{shown.length} receipt{shown.length!==1?'s':''}</Text>
      </View>

      {/*  LIST (fills remaining space)  */}
      {loading ? (
        <View style={s.loadingWrap}>
          <ActivityIndicator color={C.accent} size="large"/>
          <Text style={s.loadingTitle}>Finding your receipts</Text>
          <Text style={s.loadingText}>Loading saved trips, categories, and totals.</Text>
        </View>
      ) : (
        <FlatList
          data={shown}
          keyExtractor={r => String(r.id)}
          style={s.list}
          contentContainerStyle={s.listContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.accent}/>}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
          removeClippedSubviews={false}
          renderItem={({item:r}) => {
            const receiptCategory = getReceiptCategory(r);
            return (
              <TouchableOpacity
                style={s.card}
                onPress={() => { setSelected(r); setDeleted(false); setDeleteMode(false); }}
                activeOpacity={0.8}
              >
                <View
                  style={[
                    s.receiptIcon,
                    {
                      backgroundColor:`${receiptCategory.color}18`,
                      borderColor:`${receiptCategory.color}33`,
                      shadowColor:receiptCategory.color,
                    },
                  ]}
                  accessibilityLabel={`${receiptCategory.label} receipt`}
                >
                  <MaterialCommunityIcons name={receiptCategory.icon} size={25} color={receiptCategory.color} />
                </View>
                <View style={{flex:1}}>
                  <View style={s.cardTopLine}>
                    <Text style={s.idBadge}>#{r.id}</Text>
                    <View style={[s.categoryBadge, { backgroundColor:`${receiptCategory.color}14`, borderColor:`${receiptCategory.color}3D` }]}>
                      <Text style={[s.categoryBadgeTxt, { color:receiptCategory.color }]}>{receiptCategory.label}</Text>
                    </View>
                  </View>
                  <Text style={s.storeName}>{r.store}</Text>
                  <Text style={s.meta} numberOfLines={2}>
                    {[r.date, r.time, r.address].filter(Boolean).join('  ')}
                  </Text>
                </View>
                <View style={{alignItems:'flex-end',flexShrink:0}}>
                  <Text style={s.total}>${n(r.total).toFixed(2)}</Text>
                  {n(r.total_savings)>0 && (
                    <View style={s.pill}>
                      <Text style={s.pillTxt}>Saved ${r.total_savings!.toFixed(2)}</Text>
                    </View>
                  )}
                </View>
                <Ionicons name="chevron-forward" size={20} color={C.text3} />
              </TouchableOpacity>
            );
          }}
          ListEmptyComponent={
            <View style={s.empty}>
              <Ionicons name="receipt-outline" size={44} color={C.text3} />
              <Text style={s.emptyTitle}>{filterInfo ? 'No matching receipts' : 'No receipts yet'}</Text>
              <Text style={s.emptyTxt}>
                {filterInfo
                  ? 'Try a store name, item name, category, or receipt number.'
                  : 'Scan your first receipt to unlock price memory, spending insights, and AI answers.'}
              </Text>
              {filterInfo !== '' && (
                <TouchableOpacity
                  style={s.emptyBtn}
                  onPress={() => {
                    setStoreQ('');
                    setActiveTab('all');
                    setShown(applySort(all, 'newest'));
                    setFilterInfo('');
                  }}
                >
                  <Text style={s.emptyBtnTxt}>Clear filter</Text>
                </TouchableOpacity>
              )}
            </View>
          }
        />
      )}

      {/*  DETAIL MODAL  */}
      <Modal visible={!!selected} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setSelected(null)}>
        <SafeAreaView style={s.modal} edges={['top', 'bottom']}>
          <View style={s.modalHeader}>
            <View style={{flex:1}}>
              <Text style={s.modalStore}>{selected?.store||'Unknown Store'}</Text>
              {selected ? (
                <View style={[
                  s.categoryBadge,
                  {
                    alignSelf:'flex-start',
                    marginBottom:8,
                    backgroundColor:`${getReceiptCategory(selected).color}14`,
                    borderColor:`${getReceiptCategory(selected).color}3D`,
                  },
                ]}>
                  <Text style={[s.categoryBadgeTxt, { color:getReceiptCategory(selected).color }]}>{getReceiptCategory(selected).label}</Text>
                </View>
              ) : null}
              <Text style={s.modalMeta}>
                {[selected?.id&&`#${selected.id}`, selected?.date, selected?.time, selected?.address].filter(Boolean).join('    ')}
              </Text>
            </View>
            <IconButton name="close" label="Close receipt details" onPress={() => setSelected(null)} />
          </View>

          {deleted ? (
            <View style={s.deletedBox}>
              <Ionicons name="checkmark-circle-outline" size={48} color={C.green} style={{ marginBottom:14 }} />
              <Text style={s.deletedTitle}>Receipt Deleted</Text>
              <Text style={s.deletedSub}>Permanently removed.</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={s.modalBody}>
              {deleteMode && (
                <View style={s.deleteConfirm}>
                  <Text style={s.deleteConfirmTxt}>Delete this receipt? This cannot be undone.</Text>
                  <View style={{flexDirection:'row',gap:10,marginTop:10}}>
                    <TouchableOpacity style={s.btnYes} onPress={deleteReceipt}>
                      <Text style={{color:'#fff',fontWeight:'600',fontSize:13}}>Yes, Delete</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={s.btnNo} onPress={() => setDeleteMode(false)}>
                      <Text style={{color:C.text2,fontSize:13}}>Cancel</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              )}

              <View style={s.detailSummary}>
                <View style={s.detailTile}>
                  <Text style={s.detailLabel}>Total</Text>
                  <Text style={[s.detailValue, { color:C.accent }]}>{hasVisibleMoney(selected?.total) ? `$${n(selected?.total).toFixed(2)}` : 'Not visible'}</Text>
                </View>
                <View style={s.detailTile}>
                  <Text style={s.detailLabel}>Items</Text>
                  <Text style={s.detailValue}>{(selected?.items || []).length}</Text>
                </View>
                <View style={s.detailTile}>
                  <Text style={s.detailLabel}>Saved</Text>
                  <Text style={[s.detailValue, n(selected?.total_savings) > 0 && { color:C.green }]}>${n(selected?.total_savings).toFixed(2)}</Text>
                </View>
              </View>

              <View style={s.aiReadyBox}>
                <Text style={s.aiReadyTitle}>AI-ready receipt</Text>
                <Text style={s.aiReadyText}>Ask Agent about cheaper stores, repeated items, category spending, or whether this trip was unusual.</Text>
              </View>

              {(() => {
                const items = selected?.items || [];
                const totalPages = itemPageCount(items);
                const page = Math.min(detailItemPage, totalPages - 1);
                const start = page * INVOICE_ITEM_PAGE_SIZE + 1;
                const end = Math.min(items.length, (page + 1) * INVOICE_ITEM_PAGE_SIZE);
                return (
                  <View style={s.invoicePager}>
                    <View style={{ flex:1 }}>
                      <Text style={s.sectionTitle}>{items.length > INVOICE_ITEM_PAGE_SIZE ? 'Invoice Items' : 'Items Purchased'}</Text>
                      {items.length > INVOICE_ITEM_PAGE_SIZE ? (
                        <Text style={s.invoicePagerText}>Showing {start}-{end} of {items.length}</Text>
                      ) : null}
                    </View>
                    {items.length > INVOICE_ITEM_PAGE_SIZE ? (
                      <View style={s.pageControls}>
                        <TouchableOpacity
                          style={[s.pageBtn, page === 0 && s.pageBtnDisabled]}
                          onPress={() => setDetailItemPage(Math.max(0, page - 1))}
                          disabled={page === 0}
                        >
                          <Text style={s.pageBtnText}>Prev</Text>
                        </TouchableOpacity>
                        <Text style={s.pageCount}>{page + 1}/{totalPages}</Text>
                        <TouchableOpacity
                          style={[s.pageBtn, page >= totalPages - 1 && s.pageBtnDisabled]}
                          onPress={() => setDetailItemPage(Math.min(totalPages - 1, page + 1))}
                          disabled={page >= totalPages - 1}
                        >
                          <Text style={s.pageBtnText}>Next</Text>
                        </TouchableOpacity>
                      </View>
                    ) : null}
                  </View>
                );
              })()}
              {itemPageItems(selected?.items || [], detailItemPage).map(({ item, originalIndex }) => {
                const neg = item.price < 0;
                const ps  = neg ? `-$${Math.abs(item.price).toFixed(2)}` : `$${n(item.price).toFixed(2)}`;
                const detailLines = itemDetailLines(item);
                const itemVisual = getReceiptItemVisual(item, selected ? getReceiptCategory(selected) : undefined);
                return (
                  <View key={originalIndex} style={s.mItem}>
                    <View
                      style={[
                        s.mItemVisual,
                        {
                          backgroundColor:`${itemVisual.color}17`,
                          borderColor:`${itemVisual.color}35`,
                        },
                      ]}
                      accessibilityLabel={`${itemVisual.label} icon`}
                    >
                      {itemVisual.image ? (
                        <Image source={itemVisual.image} style={s.mItemPicture} resizeMode="contain" />
                      ) : (
                        <MaterialCommunityIcons name={itemVisual.icon} size={21} color={itemVisual.color} />
                      )}
                    </View>
                    <View style={{flex:1}}>
                      {item.code ? <Text style={s.mCode}>{item.code}</Text> : null}
                      <Text style={s.mName}>{item.name}</Text>
                      {item.corrected_by_user ? <Text style={s.correctedTxt}>Corrected</Text> : null}
                      {detailLines.length ? (
                        <View style={s.mDetailWrap}>
                          {detailLines.map((line, idx) => (
                            <Text key={`${line}-${idx}`} style={s.mDetail}>{line}</Text>
                          ))}
                        </View>
                      ) : null}
                    </View>
                    <View style={{ alignItems:'flex-end', gap:6 }}>
                      <Text style={[s.mPrice,{color:neg?C.green:C.text}]}>{ps}</Text>
                      <TouchableOpacity style={s.editItemBtn} onPress={() => startEditItem(originalIndex, item)}>
                        <Text style={s.editItemTxt}>Edit</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                );
              })}

              <Text style={[s.sectionTitle,{marginTop:20}]}>Summary</Text>
              <View style={s.totalsBox}>
                {n(selected?.subtotal)>0 && <View style={s.tRow}><Text style={s.tLbl}>Subtotal</Text><Text style={s.tVal}>${n(selected?.subtotal).toFixed(2)}</Text></View>}
                {n(selected?.discount)>0 && <View style={s.tRow}><Text style={s.tLbl}>Discount</Text><Text style={[s.tVal,{color:C.green}]}>-${n(selected?.discount).toFixed(2)}</Text></View>}
                {n(selected?.tax)>0      && <View style={s.tRow}><Text style={s.tLbl}>Tax</Text><Text style={s.tVal}>${n(selected?.tax).toFixed(2)}</Text></View>}
                <View style={[s.tRow,s.tFinal]}>
                  <Text style={s.tFinalLbl}>Total Paid</Text>
                  <Text style={s.tFinalAmt}>{hasVisibleMoney(selected?.total) ? `$${n(selected?.total).toFixed(2)}` : 'Not visible'}</Text>
                </View>
                {!hasVisibleMoney(selected?.total) ? (
                  <Text style={s.totalNote}>Final invoice total was not visible in the scanned image.</Text>
                ) : null}
              </View>

              {n(selected?.total_savings)>0 && (
                <View style={s.savingsBanner}>
                  <Text style={s.savingsBannerTxt}>  You saved ${selected!.total_savings!.toFixed(2)} on this trip!</Text>
                </View>
              )}
              {selected?.payment_method ? <Text style={s.payment}>Paid with {selected.payment_method}</Text> : null}
              {selected?.transaction_number ? <Text style={s.payment}>Transaction {selected.transaction_number}</Text> : null}
              {selected?.receipt_number ? <Text style={s.payment}>Receipt {selected.receipt_number}</Text> : null}
              {selected?.invoice_number ? <Text style={s.payment}>Invoice {selected.invoice_number}</Text> : null}
              {selected?.order_number ? <Text style={s.payment}>Order {selected.order_number}</Text> : null}

              {!deleteMode && (
                <TouchableOpacity style={s.deleteBtn} onPress={() => setDeleteMode(true)}>
                  <Text style={s.deleteBtnTxt}>  Delete Receipt</Text>
                </TouchableOpacity>
              )}
            </ScrollView>
          )}
        </SafeAreaView>
      </Modal>

      <Modal visible={!!editingItem} animationType="slide" transparent onRequestClose={() => setEditingItem(null)}>
        <View style={s.editOverlay}>
          <View style={s.editSheet}>
            <Text style={s.editTitle}>Edit Item</Text>
            <Text style={s.editHint}>Correct OCR mistakes so Price Memory learns the right price.</Text>

            <Text style={s.editLabel}>Item name</Text>
            <TextInput
              style={s.editInput}
              value={editName}
              onChangeText={setEditName}
              placeholder="Item name"
              placeholderTextColor={C.text3}
              autoCorrect={false}
            />

            <View style={s.editTwoCol}>
              <View style={{ flex:1 }}>
                <Text style={s.editLabel}>Price</Text>
                <TextInput
                  style={s.editInput}
                  value={editPrice}
                  onChangeText={setEditPrice}
                  placeholder="0.00"
                  placeholderTextColor={C.text3}
                  keyboardType="decimal-pad"
                />
              </View>
              <View style={{ flex:1 }}>
                <Text style={s.editLabel}>Qty</Text>
                <TextInput
                  style={s.editInput}
                  value={editQty}
                  onChangeText={setEditQty}
                  placeholder="1"
                  placeholderTextColor={C.text3}
                  keyboardType="decimal-pad"
                />
              </View>
            </View>

            <View style={s.editActions}>
              <TouchableOpacity style={s.editCancelBtn} onPress={() => setEditingItem(null)} disabled={editSaving}>
                <Text style={s.editCancelTxt}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.editSaveBtn, editSaving && { opacity:0.6 }]} onPress={saveEditedItem} disabled={editSaving}>
                {editSaving ? <ActivityIndicator color="#fff" size="small" /> : <Text style={s.editSaveTxt}>Save</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}

const createStyles = (C: typeof DARK_COLORS) => StyleSheet.create({
  screen:{ flex:1, backgroundColor:C.bg },

  top:{ backgroundColor:C.bg, paddingTop:8 },
  brandBar:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', paddingHorizontal:18, paddingTop:4, paddingBottom:10 },
  brandLeft:{ flexDirection:'row', alignItems:'center', gap:7 },
  miniPrismLogo:{ position:'relative', width:28, height:28 },
  miniPrismViolet:{ position:'absolute', left:2, top:2, width:16, height:23, borderRadius:6, borderBottomRightRadius:9, backgroundColor:'#6557FF', transform:[{rotate:'-8deg'}] },
  miniPrismMint:{ position:'absolute', right:2, bottom:1, width:16, height:22, borderRadius:6, borderBottomRightRadius:9, backgroundColor:'#54D9D2', opacity:0.82, transform:[{rotate:'8deg'}] },
  brandName:{ color:C.text, fontSize:13, fontWeight:'800' },
  brandAction:{ width:40, height:40, borderRadius:15, borderBottomRightRadius:7, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, alignItems:'center', justifyContent:'center', shadowColor:'#36283E', shadowOpacity:0.08, shadowRadius:14, shadowOffset:{width:0,height:7}, elevation:2 },
  hero:{ paddingHorizontal:18, paddingTop:4, paddingBottom:13 },
  heroKicker:{ color:C.accent, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:1.25, marginBottom:6 },
  heroTitle:{ color:C.text, fontSize:34, lineHeight:38, fontFamily:Platform.OS === 'android' ? 'serif' : 'Georgia', fontWeight:'400', letterSpacing:-1 },
  heroSub:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:4 },
  searchToolsRow:{ flexDirection:'row', alignItems:'center', gap:9, paddingHorizontal:16, marginBottom:10 },
  searchBox:{ flex:1, minWidth:0, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:16, flexDirection:'row', alignItems:'center', gap:8, paddingHorizontal:12 },
  searchInput:{ flex:1, color:C.text, fontSize:14, paddingVertical:12 },
  searchClear:{ paddingLeft:10, paddingVertical:8 },
  searchClearTxt:{ color:C.accent, fontSize:12, fontWeight:'800' },
  filterToggle:{ height:46, flexDirection:'row', alignItems:'center', gap:6, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:16, paddingHorizontal:13 },
  filterToggleActive:{ backgroundColor:'rgba(124,106,255,0.12)', borderColor:'rgba(124,106,255,0.38)' },
  filterToggleTxt:{ color:C.text2, fontSize:12, fontWeight:'800' },
  filterToggleTxtActive:{ color:C.accent },
  filterActiveDot:{ width:6, height:6, borderRadius:3, backgroundColor:C.green },
  filterDrawer:{ marginHorizontal:16, marginBottom:10, paddingVertical:12, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:20, overflow:'hidden' },
  filterDrawerKicker:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.7, paddingHorizontal:14, marginBottom:7 },
  categoryRow:{ gap:8, paddingHorizontal:14, paddingBottom:4 },
  categoryQuickChip:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:12, paddingHorizontal:12, paddingVertical:8 },
  categoryQuickActive:{ backgroundColor:'rgba(124,106,255,0.16)', borderColor:'rgba(124,106,255,0.42)' },
  categoryQuickTxt:{ color:C.text2, fontSize:11, fontWeight:'700' },
  categoryQuickTxtActive:{ color:C.accent },

  // Filter tabs
  tabsRow:{ flexDirection:'row', gap:6, paddingHorizontal:14, paddingVertical:6 },
  tab:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, paddingHorizontal:14, paddingVertical:8, flexShrink:0 },
  tabActive:{ backgroundColor:'rgba(124,106,255,0.15)', borderColor:'rgba(124,106,255,0.4)' },
  tabTxt:{ color:C.text2, fontSize:12, fontWeight:'500' },
  tabTxtActive:{ color:C.accent },

  // Filter panel
  filterPanel:{ paddingHorizontal:14, paddingTop:8, paddingBottom:2 },
  filterRow:{ flexDirection:'row', gap:8, alignItems:'center', marginBottom:6 },
  filterLabel:{ color:C.text3, fontSize:12, minWidth:36 },
  filterInput:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:11, padding:10, paddingHorizontal:14, color:C.text, fontSize:13 },
  filterBtn:{ backgroundColor:C.accent, borderRadius:11, paddingHorizontal:16, paddingVertical:10 },
  filterBtnTxt:{ color:'#fff', fontWeight:'600', fontSize:13 },
  filterHint:{ color:C.text3, fontSize:11, lineHeight:15, marginTop:2 },
  searchHintBox:{ backgroundColor:'rgba(124,106,255,0.06)', borderWidth:1, borderColor:'rgba(124,106,255,0.14)', borderRadius:12, padding:10 },
  receiptSummary:{ marginHorizontal:16, marginBottom:10, minHeight:50, flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:12, paddingHorizontal:15, paddingVertical:12, borderRadius:20, borderBottomRightRadius:8, backgroundColor:'#5C536B', shadowColor:'#36253F', shadowOpacity:0.18, shadowRadius:18, shadowOffset:{width:0,height:10}, elevation:5 },
  receiptSummaryLabel:{ color:'rgba(255,254,250,0.70)', fontSize:11, fontWeight:'800', flex:1 },
  receiptSummaryTotal:{ color:'#FFFEFA', fontSize:19, fontFamily:Platform.OS === 'android' ? 'serif' : 'Georgia', fontWeight:'400' },

  // Select chips (month/year/sort)
  selectChip:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, paddingHorizontal:14, paddingVertical:6, flexShrink:0 },
  selectChipActive:{ backgroundColor:'rgba(124,106,255,0.15)', borderColor:'rgba(124,106,255,0.4)' },
  selectChipTxt:{ color:C.text2, fontSize:12 },
  selectChipTxtActive:{ color:C.accent },

  // Results info bar
  infoRow:{ flexDirection:'row', justifyContent:'space-between', alignItems:'center', paddingHorizontal:16, paddingVertical:6, backgroundColor:'rgba(124,106,255,0.06)', borderTopWidth:1, borderTopColor:'rgba(124,106,255,0.15)', borderBottomWidth:1, borderBottomColor:'rgba(124,106,255,0.15)' },
  infoTxt:{ color:C.text2, fontSize:12, flex:1 },
  clearTxt:{ color:C.accent, fontSize:12, textDecorationLine:'underline', paddingLeft:8 },
  countLbl:{ color:C.text3, fontSize:11, paddingHorizontal:16, paddingBottom:4, letterSpacing:0.4 },

  // List
  list:{ flex:1 },
  listContent:{ padding:16, paddingTop:4, paddingBottom:32 },
  loadingWrap:{ flex:1, alignItems:'center', justifyContent:'center', padding:28 },
  loadingTitle:{ color:C.text, fontSize:16, fontWeight:'900', marginTop:14 },
  loadingText:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:5, textAlign:'center' },

  // Receipt cards
  card:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:22, borderBottomRightRadius:8, padding:11, marginBottom:8, flexDirection:'row', alignItems:'center', gap:11, shadowColor:'#36283E', shadowOpacity:0.09, shadowRadius:16, shadowOffset:{width:0,height:8}, elevation:3 },
  receiptIcon:{ width:48, height:48, borderRadius:15, borderWidth:1, alignItems:'center', justifyContent:'center', shadowOpacity:0.12, shadowRadius:8, shadowOffset:{width:0,height:4}, elevation:2 },
  cardTopLine:{ flexDirection:'row', alignItems:'center', gap:6, flexWrap:'wrap', marginBottom:4 },
  idBadge:{ color:C.text3, fontSize:9, fontFamily:'monospace', letterSpacing:0.5, marginBottom:3 },
  categoryBadge:{ backgroundColor:'rgba(128,111,255,0.10)', borderWidth:1, borderColor:'rgba(128,111,255,0.24)', borderRadius:8, paddingHorizontal:8, paddingVertical:3 },
  categoryBadgeTxt:{ color:C.accent, fontSize:10, fontWeight:'600' },
  storeName:{ color:C.text, fontSize:13, fontWeight:'900', marginBottom:3 },
  meta:{ color:C.text2, fontSize:11, lineHeight:16 },
  total:{ color:C.text, fontSize:15, fontFamily:Platform.OS === 'android' ? 'serif' : 'Georgia', fontWeight:'700', letterSpacing:-0.2 },
  pill:{ backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.2)', borderRadius:99, paddingHorizontal:8, paddingVertical:2, marginTop:4 },
  pillTxt:{ color:C.green, fontSize:10 },
  arrow:{ color:C.text3, fontSize:22, marginLeft:2 },

  empty:{ alignItems:'center', paddingTop:60, gap:10, paddingHorizontal:24 },
  emptyEmoji:{ fontSize:36 },
  emptyTitle:{ color:C.text, fontSize:18, fontWeight:'900', textAlign:'center' },
  emptyTxt:{ color:C.text2, fontSize:13, lineHeight:19, textAlign:'center' },
  emptyBtn:{ backgroundColor:C.accent, borderRadius:12, paddingHorizontal:16, paddingVertical:10, marginTop:4 },
  emptyBtnTxt:{ color:'#fff', fontSize:13, fontWeight:'900' },

  // Modal
  modal:{ flex:1, backgroundColor:C.bg },
  modalHeader:{ flexDirection:'row', alignItems:'flex-start', padding:20, borderBottomWidth:1, borderBottomColor:C.border, backgroundColor:C.card },
  modalStore:{ color:C.text, fontSize:20, fontWeight:'800', marginBottom:4 },
  modalMeta:{ color:C.text2, fontSize:12 },
  modalBody:{ padding:20, paddingBottom:40 },
  detailSummary:{ flexDirection:'row', gap:8, marginBottom:12 },
  detailTile:{ flex:1, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:12, minHeight:66 },
  detailLabel:{ color:C.text3, fontSize:9, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:6 },
  detailValue:{ color:C.text, fontSize:15, fontWeight:'900' },
  aiReadyBox:{ backgroundColor:'rgba(124,109,255,0.08)', borderWidth:1, borderColor:'rgba(124,109,255,0.22)', borderRadius:14, padding:12, marginBottom:18 },
  aiReadyTitle:{ color:C.text, fontSize:13, fontWeight:'900', marginBottom:4 },
  aiReadyText:{ color:C.text2, fontSize:12, lineHeight:17 },
  sectionTitle:{ color:C.text3, fontSize:10, fontWeight:'600', letterSpacing:1, textTransform:'uppercase', marginBottom:10 },
  invoicePager:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:6 },
  invoicePagerText:{ color:C.text2, fontSize:11, marginTop:-6 },
  pageControls:{ flexDirection:'row', alignItems:'center', gap:6 },
  pageBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:9, paddingHorizontal:10, paddingVertical:6 },
  pageBtnDisabled:{ opacity:0.35 },
  pageBtnText:{ color:C.accent, fontSize:11, fontWeight:'900' },
  pageCount:{ color:C.text2, fontSize:11, fontWeight:'800', minWidth:34, textAlign:'center' },
  mItem:{ flexDirection:'row', justifyContent:'space-between', alignItems:'flex-start', paddingVertical:11, borderBottomWidth:1, borderBottomColor:C.border, gap:10 },
  mItemVisual:{ width:40, height:40, borderRadius:12, borderWidth:1, alignItems:'center', justifyContent:'center', marginTop:1, flexShrink:0 },
  mItemPicture:{ width:34, height:34 },
  mCode:{ color:C.text3, fontSize:9, fontFamily:'monospace', marginBottom:2 },
  mName:{ color:C.text, fontSize:13, fontWeight:'700' },
  mDetailWrap:{ marginTop:5, gap:2 },
  mDetail:{ color:C.text2, fontSize:10, lineHeight:14 },
  mPrice:{ fontSize:13, fontWeight:'600' },
  correctedTxt:{ color:C.green, fontSize:10, marginTop:3, fontWeight:'700' },
  editItemBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:8, paddingHorizontal:9, paddingVertical:4 },
  editItemTxt:{ color:C.accent, fontSize:11, fontWeight:'800' },
  totalsBox:{ backgroundColor:C.surface2, borderRadius:16, padding:14, borderWidth:1, borderColor:C.border },
  tRow:{ flexDirection:'row', justifyContent:'space-between', paddingVertical:4 },
  tLbl:{ color:C.text2, fontSize:13 },
  tVal:{ color:C.text, fontSize:13, fontWeight:'500' },
  tFinal:{ borderTopWidth:1, borderTopColor:C.border, marginTop:6, paddingTop:10 },
  tFinalLbl:{ color:C.text, fontSize:15, fontWeight:'700' },
  tFinalAmt:{ color:C.accent, fontSize:15, fontWeight:'800' },
  totalNote:{ color:C.text2, fontSize:11, lineHeight:16, marginTop:8 },
  savingsBanner:{ marginTop:12, padding:10, backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.25)', borderRadius:10 },
  savingsBannerTxt:{ color:C.green, fontWeight:'600', fontSize:13, textAlign:'center' },
  payment:{ color:C.text3, fontSize:11, textAlign:'center', marginTop:10 },
  deleteBtn:{ marginTop:20, padding:14, backgroundColor:'rgba(255,107,107,0.08)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:12, alignItems:'center' },
  deleteBtnTxt:{ color:C.red, fontSize:14, fontWeight:'500' },
  deleteConfirm:{ backgroundColor:'rgba(255,107,107,0.07)', borderWidth:1, borderColor:'rgba(255,107,107,0.22)', borderRadius:12, padding:14, marginBottom:16 },
  deleteConfirmTxt:{ color:C.text, fontSize:13 },
  btnYes:{ flex:1, padding:10, backgroundColor:C.red, borderRadius:10, alignItems:'center' },
  btnNo:{ flex:1, padding:10, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:10, alignItems:'center' },
  deletedBox:{ flex:1, alignItems:'center', justifyContent:'center', padding:40 },
  deletedTitle:{ color:C.text, fontSize:20, fontWeight:'700', marginBottom:6 },
  deletedSub:{ color:C.text2, fontSize:13 },
  editOverlay:{ flex:1, backgroundColor:'rgba(0,0,0,0.58)', justifyContent:'flex-end' },
  editSheet:{ backgroundColor:C.card, borderTopLeftRadius:24, borderTopRightRadius:24, padding:20, borderWidth:1, borderColor:C.border },
  editTitle:{ color:C.text, fontSize:20, fontWeight:'900', marginBottom:4 },
  editHint:{ color:C.text2, fontSize:12, lineHeight:17, marginBottom:16 },
  editLabel:{ color:C.text3, fontSize:11, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:6 },
  editInput:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, color:C.text, paddingHorizontal:14, paddingVertical:12, fontSize:14, marginBottom:12 },
  editTwoCol:{ flexDirection:'row', gap:10 },
  editActions:{ flexDirection:'row', gap:10, marginTop:4 },
  editCancelBtn:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:14, alignItems:'center' },
  editCancelTxt:{ color:C.text2, fontWeight:'800' },
  editSaveBtn:{ flex:1, backgroundColor:C.accent, borderRadius:12, padding:14, alignItems:'center' },
  editSaveTxt:{ color:'#fff', fontWeight:'900' },
});
