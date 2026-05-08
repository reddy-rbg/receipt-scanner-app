import { useState } from 'react';
import { useTheme } from '../themeStore';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';
const n=(v:any)=>parseFloat(v)||0;

export default function ShoppingScreen(){
  const { colors: C } = useTheme();
  const [input,setInput]=useState('');
  const [list,setList]=useState<string[]>([]);
  const [loading,setLoading]=useState(false);
  const [result,setResult]=useState<any>(null);
  const [error,setError]=useState('');

  function addItem(){
    const v=input.trim().toLowerCase();
    if(!v) return;
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

  const recs=result?.recommendations||[];
  const summary=result?.summary||{};
  const notFound=result?.not_found||[];

  return(
    <ScrollView style={[s.scroll,{backgroundColor:C.bg}]} contentContainerStyle={s.container} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

      <View style={[s.card,{backgroundColor:C.surface,borderColor:C.border}]}>
        <View style={s.cardRow}>
          <View style={[s.cardIcon,{backgroundColor:'rgba(74,222,128,0.18)'}]}><Text>🛒</Text></View>
          <Text style={[s.cardTitle,{color:C.text}]}>Shopping List Optimizer</Text>
        </View>
        <Text style={[s.desc,{color:C.text2}]}>Add items and AI finds the cheapest store from your real purchase history.</Text>

        <View style={s.inputRow}>
          <TextInput
            style={[s.input,{backgroundColor:C.surface2,borderColor:C.border,color:C.text}]}
            placeholder="e.g. milk, chicken, bread..."
            placeholderTextColor={C.text3} value={input}
            onChangeText={setInput} onSubmitEditing={addItem} returnKeyType="done"
          />
          <TouchableOpacity style={[s.addBtn,{backgroundColor:C.accent}]} onPress={addItem} activeOpacity={0.8}>
            <Text style={s.addBtnTxt}>+ Add</Text>
          </TouchableOpacity>
        </View>

        {list.length>0&&(
          <View style={s.tags}>
            {list.map(item=>(
              <View key={item} style={s.tag}>
                <Text style={[s.tagTxt,{color:C.text}]}>{item}</Text>
                <TouchableOpacity onPress={()=>removeItem(item)} hitSlop={{top:8,bottom:8,left:8,right:8}}>
                  <Text style={[s.tagX,{color:C.text3}]}>×</Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>
        )}

        {error!==''&&<View style={s.errBox}><Text style={[s.errTxt,{color:C.red}]}>⚠  {error}</Text></View>}

        {list.length>0&&(
          <TouchableOpacity style={[s.optimizeBtn,loading&&{opacity:0.5},{backgroundColor:C.accent}]} onPress={optimize} disabled={loading} activeOpacity={0.85}>
            {loading?<ActivityIndicator color="#fff" size="small"/>:<Text style={s.optimizeBtnTxt}>🛒  Optimize My Shopping List</Text>}
          </TouchableOpacity>
        )}
      </View>

      {result&&(
        <>
          {(summary.total_estimated_cost||summary.total_savings)&&(
            <View style={[s.summaryCard,{backgroundColor:C.surface2}]}>
              <View style={s.summaryGrid}>
                <View style={s.summaryItem}>
                  <Text style={[s.summaryVal,{color:C.accent}]}>${n(summary.total_estimated_cost).toFixed(2)}</Text>
                  <Text style={[s.summaryLbl,{color:C.text3}]}>Estimated Total</Text>
                </View>
                <View style={s.summaryItem}>
                  <Text style={[s.summaryVal,{color:C.green}]}>${n(summary.total_savings).toFixed(2)}</Text>
                  <Text style={[s.summaryLbl,{color:C.text3}]}>Total Savings</Text>
                </View>
                <View style={s.summaryItem}>
                  <Text style={[s.summaryVal,{color:C.accent2}]}>{(summary.stores_to_visit||[]).length}</Text>
                  <Text style={[s.summaryLbl,{color:C.text3}]}>Stores</Text>
                </View>
              </View>
              {(summary.stores_to_visit||[]).length>0&&(
                <Text style={[s.summaryStores,{color:C.text2}]}>🏪  {summary.stores_to_visit.join(', ')}</Text>
              )}
              {summary.tip&&(
                <View style={s.tipBox}><Text style={[s.tipTxt,{color:C.accent3}]}>💡  {summary.tip}</Text></View>
              )}
            </View>
          )}

          {recs.map((rec:any,i:number)=>(
            <View key={i} style={[s.recCard,{backgroundColor:C.surface2,borderColor:C.border},!rec.found&&s.recCardNotFound]}>
              {!rec.found?(
                <View style={s.notFoundItem}>
                  <View style={{flex:1}}>
                    <Text style={[s.recName,{color:C.text}]}>{rec.item}</Text>
                    <Text style={[s.notFoundHint,{color:C.text3}]}>No history — scan a receipt with this item first</Text>
                  </View>
                  <Text style={{fontSize:22}}>❓</Text>
                </View>
              ):(
                <>
                  <View style={s.recHeader}>
                    <View style={{flex:1}}>
                      <View style={s.recNameRow}>
                        <Text style={[s.recName,{color:C.text}]}>{rec.item}</Text>
                        {n(rec.savings_vs_most_expensive)>0&&(
                          <View style={s.saveBadge}>
                            <Text style={[s.saveBadgeTxt,{color:C.green}]}>Save ${n(rec.savings_vs_most_expensive).toFixed(2)}</Text>
                          </View>
                        )}
                      </View>
                      <View style={s.storeBadge}>
                        <Text style={[s.storeBadgeTxt,{color:C.accent3}]}>🏪  Buy at {rec.best_store}</Text>
                      </View>
                      {rec.last_bought&&<Text style={[s.lastBought,{color:C.text3}]}>Last bought: {rec.last_bought}</Text>}
                    </View>
                    <View style={{alignItems:'flex-end'}}>
                      <Text style={[s.bestPrice,{color:C.green}]}>${n(rec.price).toFixed(2)}</Text>
                      <Text style={[s.perUnit,{color:C.text3}]}>{rec.unit&&rec.unit!=='each'?`per ${rec.unit}`:'each'}</Text>
                    </View>
                  </View>
                  {(rec.all_options||[]).length>1&&(
                    <View style={[s.options,{borderTopColor:C.border}]}>
                      <Text style={[s.optionsLbl,{color:C.text3}]}>Other options:</Text>
                      <View style={s.optionsRow}>
                        {rec.all_options.map((opt:any,j:number)=>(
                          <View key={j} style={[s.optChip,{backgroundColor:C.surface,borderColor:C.border}]}>
                            <Text style={[s.optChipTxt,{color:C.text2}]}>{opt.store}: ${n(opt.price).toFixed(2)}{opt.unit&&opt.unit!=='each'?`/${opt.unit}`:''}</Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  )}
                </>
              )}
            </View>
          ))}

          {notFound.length>0&&(
            <View style={s.nfBox}>
              <Text style={[s.nfTxt,{color:C.text2}]}>⚠  No history for: <Text style={{fontWeight:'700',color:C.text}}>{notFound.join(', ')}</Text></Text>
              <Text style={[s.nfHint,{color:C.text3}]}>Scan receipts containing these items first.</Text>
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

const s=StyleSheet.create({
  scroll:{flex:1},
  container:{padding:16,paddingBottom:40},
  card:{borderRadius:20,borderWidth:1,padding:20,marginBottom:16},
  cardRow:{flexDirection:'row',alignItems:'center',gap:10,marginBottom:14},
  cardIcon:{width:30,height:30,borderRadius:9,alignItems:'center',justifyContent:'center'},
  cardTitle:{fontSize:15,fontWeight:'700'},
  desc:{fontSize:12,lineHeight:18,marginBottom:14},
  inputRow:{flexDirection:'row',gap:10,alignItems:'center'},
  input:{flex:1,borderWidth:1,borderRadius:11,padding:12,paddingHorizontal:14,fontSize:14},
  addBtn:{borderRadius:11,paddingHorizontal:18,paddingVertical:13},
  addBtnTxt:{color:'#fff',fontWeight:'700',fontSize:14},
  tags:{flexDirection:'row',flexWrap:'wrap',gap:8,marginTop:12},
  tag:{flexDirection:'row',alignItems:'center',gap:6,backgroundColor:'rgba(124,106,255,0.1)',borderWidth:1,borderColor:'rgba(124,106,255,0.25)',borderRadius:99,paddingHorizontal:12,paddingVertical:5},
  tagTxt:{fontSize:13},
  tagX:{fontSize:18,lineHeight:20},
  errBox:{marginTop:12,padding:12,backgroundColor:'rgba(255,107,107,0.08)',borderWidth:1,borderColor:'rgba(255,107,107,0.2)',borderRadius:10},
  errTxt:{fontSize:12},
  optimizeBtn:{borderRadius:12,padding:15,alignItems:'center',marginTop:14},
  optimizeBtnTxt:{color:'#fff',fontWeight:'700',fontSize:14},
  summaryCard:{borderRadius:16,borderWidth:1,borderColor:'rgba(106,255,212,0.2)',padding:18,marginBottom:12},
  summaryGrid:{flexDirection:'row',marginBottom:14},
  summaryItem:{flex:1,alignItems:'center'},
  summaryVal:{fontSize:22,fontWeight:'800',letterSpacing:-0.5,marginBottom:4},
  summaryLbl:{fontSize:10,textTransform:'uppercase',letterSpacing:0.5},
  summaryStores:{fontSize:13,marginBottom:10},
  tipBox:{backgroundColor:'rgba(106,255,212,0.06)',borderWidth:1,borderColor:'rgba(106,255,212,0.15)',borderRadius:10,padding:10},
  tipTxt:{fontSize:13},
  recCard:{borderWidth:1,borderRadius:14,padding:16,marginBottom:10},
  recCardNotFound:{borderColor:'rgba(251,191,36,0.2)',backgroundColor:'rgba(251,191,36,0.04)'},
  notFoundItem:{flexDirection:'row',alignItems:'center',gap:10},
  notFoundHint:{fontSize:12,marginTop:4},
  recHeader:{flexDirection:'row',justifyContent:'space-between',alignItems:'flex-start',marginBottom:10},
  recNameRow:{flexDirection:'row',alignItems:'center',gap:8,flexWrap:'wrap',marginBottom:6},
  recName:{fontSize:14,fontWeight:'700',textTransform:'capitalize'},
  saveBadge:{backgroundColor:'rgba(74,222,128,0.12)',borderWidth:1,borderColor:'rgba(74,222,128,0.3)',borderRadius:99,paddingHorizontal:8,paddingVertical:2},
  saveBadgeTxt:{fontSize:11,fontWeight:'600'},
  storeBadge:{alignSelf:'flex-start',backgroundColor:'rgba(106,255,212,0.1)',borderWidth:1,borderColor:'rgba(106,255,212,0.25)',borderRadius:99,paddingHorizontal:10,paddingVertical:3,marginBottom:4},
  storeBadgeTxt:{fontSize:12,fontWeight:'600'},
  lastBought:{fontSize:11},
  bestPrice:{fontSize:24,fontWeight:'800'},
  perUnit:{fontSize:11,textAlign:'right'},
  options:{borderTopWidth:1,paddingTop:10},
  optionsLbl:{fontSize:11,marginBottom:6},
  optionsRow:{flexDirection:'row',flexWrap:'wrap',gap:6},
  optChip:{borderWidth:1,borderRadius:8,paddingHorizontal:10,paddingVertical:4},
  optChipTxt:{fontSize:11},
  nfBox:{backgroundColor:'rgba(251,191,36,0.06)',borderWidth:1,borderColor:'rgba(251,191,36,0.2)',borderRadius:12,padding:14,marginBottom:10},
  nfTxt:{fontSize:13,marginBottom:4},
  nfHint:{fontSize:11},
});
