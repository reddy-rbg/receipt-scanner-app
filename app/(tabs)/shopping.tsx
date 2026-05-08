import { useState } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';
const C = {
  bg:'#080810',surface:'#0f0f1a',surface2:'#16162a',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff',accent2:'#ff6a9e',accent3:'#6affd4',
  text:'#ede8ff',text2:'#7e7a9a',text3:'#3d3a55',
  green:'#4ade80',gold:'#fbbf24',
};
const n=(v:any)=>parseFloat(v)||0;

export default function ShoppingScreen(){
  const [input,setInput]=useState('');
  const [list,setList]=useState<string[]>([]);
  const [loading,setLoading]=useState(false);
  const [result,setResult]=useState<any>(null);
  const [error,setError]=useState('');

  function addItem(){
    const v=input.trim().toLowerCase();
    if(!v){return;}
    if(!list.includes(v)) setList(p=>[...p,v]);
    setInput('');setResult(null);setError('');
  }

  function removeItem(item:string){
    setList(p=>p.filter(i=>i!==item));
    setResult(null);
  }

  async function optimize(){
    if(!list.length) return;
    setLoading(true);setResult(null);setError('');
    try{
      const res=await fetch(`${API}/optimize-shopping-list`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({items:list}),
      });
      const data=await res.json();
      if(!res.ok||data.error){setError(data.error||data.detail||`Error ${res.status}`);return;}
      setResult(data);
    }catch(e:any){
      setError('Could not connect to server. Check your connection.');
    }finally{setLoading(false);}
  }

  // ✅ Backend returns:
  // data.recommendations = [{item, found, best_store, price, unit, savings_vs_most_expensive, last_bought, all_options:[{store,price,unit}]}]
  // data.summary = {total_estimated_cost, total_savings, stores_to_visit:[], tip}
  // data.not_found = []

  const recs = result?.recommendations || [];
  const summary = result?.summary || {};
  const notFound = result?.not_found || [];

  return(
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

      {/* INPUT CARD */}
      <View style={s.card}>
        <View style={s.cardRow}>
          <View style={[s.cardIcon,{backgroundColor:'rgba(74,222,128,0.18)'}]}><Text>🛒</Text></View>
          <Text style={s.cardTitle}>Shopping List Optimizer</Text>
        </View>
        <Text style={s.desc}>Add items and AI finds the cheapest store from your real purchase history.</Text>

        <View style={s.inputRow}>
          <TextInput
            style={s.input} placeholder="e.g. milk, chicken, bread..."
            placeholderTextColor={C.text3} value={input}
            onChangeText={setInput} onSubmitEditing={addItem} returnKeyType="done"
          />
          <TouchableOpacity style={s.addBtn} onPress={addItem} activeOpacity={0.8}>
            <Text style={s.addBtnTxt}>+ Add</Text>
          </TouchableOpacity>
        </View>

        {list.length>0&&(
          <View style={s.tags}>
            {list.map(item=>(
              <View key={item} style={s.tag}>
                <Text style={s.tagTxt}>{item}</Text>
                <TouchableOpacity onPress={()=>removeItem(item)} hitSlop={{top:8,bottom:8,left:8,right:8}}>
                  <Text style={s.tagX}>×</Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>
        )}

        {error!==''&&<View style={s.errBox}><Text style={s.errTxt}>⚠  {error}</Text></View>}

        {list.length>0&&(
          <TouchableOpacity style={[s.optimizeBtn,loading&&{opacity:0.5}]} onPress={optimize} disabled={loading} activeOpacity={0.85}>
            {loading?<ActivityIndicator color="#fff" size="small"/>:<Text style={s.optimizeBtnTxt}>🛒  Optimize My Shopping List</Text>}
          </TouchableOpacity>
        )}
      </View>

      {/* RESULTS */}
      {result&&(
        <>
          {/* Summary */}
          {(summary.total_estimated_cost||summary.total_savings)&&(
            <View style={s.summaryCard}>
              <View style={s.summaryGrid}>
                <View style={s.summaryItem}>
                  <Text style={[s.summaryVal,{color:C.accent}]}>${n(summary.total_estimated_cost).toFixed(2)}</Text>
                  <Text style={s.summaryLbl}>Estimated Total</Text>
                </View>
                <View style={s.summaryItem}>
                  <Text style={[s.summaryVal,{color:C.green}]}>${n(summary.total_savings).toFixed(2)}</Text>
                  <Text style={s.summaryLbl}>Total Savings</Text>
                </View>
                <View style={s.summaryItem}>
                  <Text style={[s.summaryVal,{color:C.accent2}]}>{(summary.stores_to_visit||[]).length}</Text>
                  <Text style={s.summaryLbl}>Stores</Text>
                </View>
              </View>
              {(summary.stores_to_visit||[]).length>0&&(
                <Text style={s.summaryStores}>🏪  {summary.stores_to_visit.join(', ')}</Text>
              )}
              {summary.tip&&(
                <View style={s.tipBox}><Text style={s.tipTxt}>💡  {summary.tip}</Text></View>
              )}
            </View>
          )}

          {/* Item recommendations */}
          {recs.map((rec:any,i:number)=>(
            <View key={i} style={[s.recCard,!rec.found&&s.recCardNotFound]}>
              {!rec.found?(
                <View style={s.notFoundItem}>
                  <View style={{flex:1}}>
                    <Text style={s.recName}>{rec.item}</Text>
                    <Text style={s.notFoundHint}>No history — scan a receipt with this item first</Text>
                  </View>
                  <Text style={{fontSize:22}}>❓</Text>
                </View>
              ):(
                <>
                  <View style={s.recHeader}>
                    <View style={{flex:1}}>
                      <View style={s.recNameRow}>
                        <Text style={s.recName}>{rec.item}</Text>
                        {n(rec.savings_vs_most_expensive)>0&&(
                          <View style={s.saveBadge}>
                            <Text style={s.saveBadgeTxt}>Save ${n(rec.savings_vs_most_expensive).toFixed(2)}</Text>
                          </View>
                        )}
                      </View>
                      <View style={s.storeBadge}>
                        <Text style={s.storeBadgeTxt}>🏪  Buy at {rec.best_store}</Text>
                      </View>
                      {rec.last_bought&&<Text style={s.lastBought}>Last bought: {rec.last_bought}</Text>}
                    </View>
                    <View style={{alignItems:'flex-end'}}>
                      <Text style={s.bestPrice}>${n(rec.price).toFixed(2)}</Text>
                      <Text style={s.perUnit}>{rec.unit&&rec.unit!=='each'?`per ${rec.unit}`:'each'}</Text>
                    </View>
                  </View>

                  {(rec.all_options||[]).length>1&&(
                    <View style={s.options}>
                      <Text style={s.optionsLbl}>Other options:</Text>
                      <View style={s.optionsRow}>
                        {rec.all_options.map((opt:any,j:number)=>(
                          <View key={j} style={s.optChip}>
                            <Text style={s.optChipTxt}>{opt.store}: ${n(opt.price).toFixed(2)}{opt.unit&&opt.unit!=='each'?`/${opt.unit}`:''}</Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  )}
                </>
              )}
            </View>
          ))}

          {/* Not found */}
          {notFound.length>0&&(
            <View style={s.nfBox}>
              <Text style={s.nfTxt}>⚠  No history for: <Text style={{fontWeight:'700',color:C.text}}>{notFound.join(', ')}</Text></Text>
              <Text style={s.nfHint}>Scan receipts containing these items first.</Text>
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

const s=StyleSheet.create({
  scroll:{flex:1,backgroundColor:C.bg},
  container:{padding:16,paddingBottom:40},
  card:{backgroundColor:C.surface,borderRadius:20,borderWidth:1,borderColor:C.border,padding:20,marginBottom:16},
  cardRow:{flexDirection:'row',alignItems:'center',gap:10,marginBottom:14},
  cardIcon:{width:30,height:30,borderRadius:9,alignItems:'center',justifyContent:'center'},
  cardTitle:{color:C.text,fontSize:15,fontWeight:'700'},
  desc:{color:C.text2,fontSize:12,lineHeight:18,marginBottom:14},
  inputRow:{flexDirection:'row',gap:10,alignItems:'center'},
  input:{flex:1,backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:11,padding:12,paddingHorizontal:14,color:C.text,fontSize:14},
  addBtn:{backgroundColor:C.accent,borderRadius:11,paddingHorizontal:18,paddingVertical:13},
  addBtnTxt:{color:'#fff',fontWeight:'700',fontSize:14},
  tags:{flexDirection:'row',flexWrap:'wrap',gap:8,marginTop:12},
  tag:{flexDirection:'row',alignItems:'center',gap:6,backgroundColor:'rgba(124,106,255,0.1)',borderWidth:1,borderColor:'rgba(124,106,255,0.25)',borderRadius:99,paddingHorizontal:12,paddingVertical:5},
  tagTxt:{color:C.text,fontSize:13},
  tagX:{color:C.text3,fontSize:18,lineHeight:20},
  errBox:{marginTop:12,padding:12,backgroundColor:'rgba(255,107,107,0.08)',borderWidth:1,borderColor:'rgba(255,107,107,0.2)',borderRadius:10},
  errTxt:{color:C.red,fontSize:12},
  optimizeBtn:{backgroundColor:C.accent,borderRadius:12,padding:15,alignItems:'center',marginTop:14,shadowColor:C.accent,shadowOpacity:0.35,shadowRadius:12},
  optimizeBtnTxt:{color:'#fff',fontWeight:'700',fontSize:14},
  // Summary
  summaryCard:{backgroundColor:C.surface2,borderRadius:16,borderWidth:1,borderColor:'rgba(106,255,212,0.2)',padding:18,marginBottom:12},
  summaryGrid:{flexDirection:'row',marginBottom:14},
  summaryItem:{flex:1,alignItems:'center'},
  summaryVal:{fontSize:22,fontWeight:'800',letterSpacing:-0.5,marginBottom:4},
  summaryLbl:{color:C.text3,fontSize:10,textTransform:'uppercase',letterSpacing:0.5},
  summaryStores:{color:C.text2,fontSize:13,marginBottom:10},
  tipBox:{backgroundColor:'rgba(106,255,212,0.06)',borderWidth:1,borderColor:'rgba(106,255,212,0.15)',borderRadius:10,padding:10},
  tipTxt:{color:C.accent3,fontSize:13},
  // Rec cards
  recCard:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:14,padding:16,marginBottom:10},
  recCardNotFound:{borderColor:'rgba(251,191,36,0.2)',backgroundColor:'rgba(251,191,36,0.04)'},
  notFoundItem:{flexDirection:'row',alignItems:'center',gap:10},
  notFoundHint:{color:C.text3,fontSize:12,marginTop:4},
  recHeader:{flexDirection:'row',justifyContent:'space-between',alignItems:'flex-start',marginBottom:10},
  recNameRow:{flexDirection:'row',alignItems:'center',gap:8,flexWrap:'wrap',marginBottom:6},
  recName:{color:C.text,fontSize:14,fontWeight:'700',textTransform:'capitalize'},
  saveBadge:{backgroundColor:'rgba(74,222,128,0.12)',borderWidth:1,borderColor:'rgba(74,222,128,0.3)',borderRadius:99,paddingHorizontal:8,paddingVertical:2},
  saveBadgeTxt:{color:C.green,fontSize:11,fontWeight:'600'},
  storeBadge:{alignSelf:'flex-start',backgroundColor:'rgba(106,255,212,0.1)',borderWidth:1,borderColor:'rgba(106,255,212,0.25)',borderRadius:99,paddingHorizontal:10,paddingVertical:3,marginBottom:4},
  storeBadgeTxt:{color:C.accent3,fontSize:12,fontWeight:'600'},
  lastBought:{color:C.text3,fontSize:11},
  bestPrice:{color:C.green,fontSize:24,fontWeight:'800'},
  perUnit:{color:C.text3,fontSize:11,textAlign:'right'},
  options:{borderTopWidth:1,borderTopColor:C.border,paddingTop:10},
  optionsLbl:{color:C.text3,fontSize:11,marginBottom:6},
  optionsRow:{flexDirection:'row',flexWrap:'wrap',gap:6},
  optChip:{backgroundColor:C.surface,borderWidth:1,borderColor:C.border,borderRadius:8,paddingHorizontal:10,paddingVertical:4},
  optChipTxt:{color:C.text2,fontSize:11},
  nfBox:{backgroundColor:'rgba(251,191,36,0.06)',borderWidth:1,borderColor:'rgba(251,191,36,0.2)',borderRadius:12,padding:14,marginBottom:10},
  nfTxt:{color:C.text2,fontSize:13,marginBottom:4},
  nfHint:{color:C.text3,fontSize:11},
});
