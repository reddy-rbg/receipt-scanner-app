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
  green:'#4ade80',red:'#ff6b6b',gold:'#fbbf24',
};
const n=(v:any)=>parseFloat(v)||0;

export default function PriceTrackerScreen(){
  const [input,setInput]=useState('');
  const [loading,setLoading]=useState(false);
  const [result,setResult]=useState<any>(null);
  const [itemName,setItemName]=useState('');
  const [error,setError]=useState('');

  async function track(){
    const item=input.trim();
    if(!item) return;
    setLoading(true);setResult(null);setError('');setItemName(item);
    try{
      // ✅ GET /price-history/{item}
      // returns { stats:{lowest,highest,average,current,trend}, data_points:[{item,store,date,price,unit_price,unit,quantity}] }
      const res=await fetch(`${API}/price-history/${encodeURIComponent(item)}`);
      const data=await res.json();
      if(data.message){setError(data.message);return;}
      setResult(data);
    }catch(e:any){
      setError('Could not connect to server.');
    }finally{setLoading(false);}
  }

  const stats=result?.stats||{};
  const points:any[]=result?.data_points||[];

  // Trend config
  const trendIcon=stats.trend==='up'?'📈':stats.trend==='down'?'📉':'➡️';
  const trendColor=stats.trend==='up'?C.red:stats.trend==='down'?C.green:C.text2;
  const trendText=stats.trend==='up'?'Rising':stats.trend==='down'?'Falling':'Stable';

  // Group points by store for display
  const stores=[...new Set(points.map((p:any)=>p.store))];
  const storeColors=[C.accent,C.accent2,C.accent3,C.gold,C.green];

  return(
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

      {/* HEADER CARD */}
      <View style={s.card}>
        <View style={s.cardRow}>
          <View style={[s.cardIcon,{backgroundColor:'rgba(255,106,158,0.18)'}]}><Text>📈</Text></View>
          <Text style={s.cardTitle}>Price Trend Tracker</Text>
        </View>
        <Text style={s.desc}>Track how prices change over time across your receipt history.</Text>

        <View style={s.inputRow}>
          <TextInput
            style={s.input}
            placeholder="e.g. milk, chicken, paprika..."
            placeholderTextColor={C.text3}
            value={input}
            onChangeText={setInput}
            onSubmitEditing={track}
            returnKeyType="search"
          />
          <TouchableOpacity style={[s.trackBtn,loading&&{opacity:0.5}]} onPress={track} disabled={loading} activeOpacity={0.85}>
            {loading?<ActivityIndicator color="#fff" size="small"/>:<Text style={s.trackBtnTxt}>Track</Text>}
          </TouchableOpacity>
        </View>

        {error!==''&&<View style={s.errBox}><Text style={s.errTxt}>⚠  {error}</Text></View>}
      </View>

      {/* RESULTS */}
      {result&&(
        <>
          {/* Stats grid */}
          <View style={s.statsGrid}>
            <View style={s.statBox}>
              <Text style={[s.statVal,{color:C.green}]}>${stats.lowest||'—'}</Text>
              <Text style={s.statLbl}>Lowest Paid</Text>
            </View>
            <View style={s.statBox}>
              <Text style={[s.statVal,{color:C.red}]}>${stats.highest||'—'}</Text>
              <Text style={s.statLbl}>Highest Paid</Text>
            </View>
            <View style={s.statBox}>
              <Text style={[s.statVal,{color:C.accent}]}>${stats.average||'—'}</Text>
              <Text style={s.statLbl}>Average</Text>
            </View>
            <View style={s.statBox}>
              <Text style={[s.statVal,{color:trendColor}]}>{trendIcon}</Text>
              <Text style={s.statLbl}>{trendText}</Text>
              <Text style={[s.statSub,{color:trendColor}]}>Now: ${stats.current||'—'}</Text>
            </View>
          </View>

          {/* Price history title */}
          <Text style={s.sectionTitle}>Price History for "{itemName}"</Text>

          {/* Store legend */}
          {stores.length>1&&(
            <View style={s.legendRow}>
              {stores.map((store,i)=>(
                <View key={i} style={s.legendItem}>
                  <View style={[s.legendDot,{backgroundColor:storeColors[i%storeColors.length]}]}/>
                  <Text style={s.legendTxt}>{store}</Text>
                </View>
              ))}
            </View>
          )}

          {/* Simple bar chart visual */}
          {points.length<2?(
            <View style={s.noDataBox}>
              <Text style={s.noDataTxt}>Only one data point found.</Text>
              <Text style={s.noDataSub}>Scan more receipts with this item to see price trends.</Text>
            </View>
          ):(
            <View style={s.chartCard}>
              {/* Mini visual price timeline */}
              <View style={s.timeline}>
                {points.slice(-8).map((p:any,i:number)=>{
                  const storeIdx=stores.indexOf(p.store);
                  const color=storeColors[storeIdx%storeColors.length];
                  const maxP=Math.max(...points.map((x:any)=>n(x.unit_price)));
                  const barH=maxP>0?Math.max(20,(n(p.unit_price)/maxP)*100):20;
                  return(
                    <View key={i} style={s.barWrap}>
                      <Text style={[s.barLabel,{color}]}>${n(p.unit_price).toFixed(2)}</Text>
                      <View style={[s.bar,{height:barH,backgroundColor:color+'33',borderColor:color}]}/>
                      <Text style={s.barDate} numberOfLines={1}>{(p.date||'').slice(5)}</Text>
                      <Text style={s.barStore} numberOfLines={1}>{p.store?.split(' ')[0]}</Text>
                    </View>
                  );
                })}
              </View>
            </View>
          )}

          {/* All purchase history */}
          <View style={s.historyCard}>
            <Text style={s.historyTitle}>All Purchases</Text>
            {[...points].reverse().map((p:any,i:number)=>{
              const storeIdx=stores.indexOf(p.store);
              const color=storeColors[storeIdx%storeColors.length];
              const priceLabel=p.unit&&p.unit!=='each'
                ?`$${n(p.unit_price).toFixed(2)}/${p.unit} (${p.quantity} ${p.unit} = $${n(p.price).toFixed(2)})`
                :`$${n(p.unit_price).toFixed(2)}`;
              return(
                <View key={i} style={s.histRow}>
                  <View style={{flex:1}}>
                    <Text style={s.histItem}>{p.item}</Text>
                    <View style={s.histMeta}>
                      <View style={[s.histDot,{backgroundColor:color}]}/>
                      <Text style={s.histStore}>{p.store}</Text>
                      <Text style={s.histDate}>· {p.date}</Text>
                    </View>
                  </View>
                  <Text style={[s.histPrice,{color}]}>{priceLabel}</Text>
                </View>
              );
            })}
          </View>
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
  trackBtn:{backgroundColor:C.accent2,borderRadius:11,paddingHorizontal:18,paddingVertical:13},
  trackBtnTxt:{color:'#fff',fontWeight:'700',fontSize:14},
  errBox:{marginTop:12,padding:12,backgroundColor:'rgba(255,107,107,0.08)',borderWidth:1,borderColor:'rgba(255,107,107,0.2)',borderRadius:10},
  errTxt:{color:C.red,fontSize:12},
  statsGrid:{flexDirection:'row',flexWrap:'wrap',gap:10,marginBottom:16},
  statBox:{flex:1,minWidth:'45%',backgroundColor:C.surface2,borderRadius:14,padding:14,borderWidth:1,borderColor:C.border,alignItems:'center'},
  statVal:{fontSize:18,fontWeight:'800',letterSpacing:-0.5,marginBottom:4},
  statLbl:{color:C.text3,fontSize:10,textTransform:'uppercase',letterSpacing:0.5},
  statSub:{fontSize:11,marginTop:2},
  sectionTitle:{color:C.text,fontSize:14,fontWeight:'700',marginBottom:10},
  legendRow:{flexDirection:'row',flexWrap:'wrap',gap:10,marginBottom:12},
  legendItem:{flexDirection:'row',alignItems:'center',gap:5},
  legendDot:{width:8,height:8,borderRadius:4},
  legendTxt:{color:C.text2,fontSize:12},
  noDataBox:{backgroundColor:C.surface2,borderRadius:14,padding:24,alignItems:'center',marginBottom:14,borderWidth:1,borderColor:C.border},
  noDataTxt:{color:C.text,fontSize:14,fontWeight:'600',marginBottom:6},
  noDataSub:{color:C.text3,fontSize:12,textAlign:'center'},
  chartCard:{backgroundColor:C.surface2,borderRadius:14,borderWidth:1,borderColor:C.border,padding:16,marginBottom:14},
  timeline:{flexDirection:'row',alignItems:'flex-end',gap:8,height:160,paddingTop:30},
  barWrap:{flex:1,alignItems:'center',justifyContent:'flex-end'},
  barLabel:{fontSize:9,marginBottom:4,fontWeight:'600'},
  bar:{width:'100%',borderRadius:4,borderWidth:1,minHeight:20},
  barDate:{fontSize:8,color:C.text3,marginTop:4,textAlign:'center'},
  barStore:{fontSize:8,color:C.text3,textAlign:'center'},
  historyCard:{backgroundColor:C.surface2,borderRadius:14,borderWidth:1,borderColor:C.border,padding:16},
  historyTitle:{color:C.text2,fontSize:11,fontWeight:'600',letterSpacing:0.5,textTransform:'uppercase',marginBottom:12},
  histRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'flex-start',paddingVertical:10,borderBottomWidth:1,borderBottomColor:C.border,gap:10},
  histItem:{color:C.text,fontSize:13,fontWeight:'500',marginBottom:4},
  histMeta:{flexDirection:'row',alignItems:'center',gap:5},
  histDot:{width:6,height:6,borderRadius:3},
  histStore:{color:C.text3,fontSize:11},
  histDate:{color:C.text3,fontSize:11},
  histPrice:{fontSize:13,fontWeight:'700'},
});
