import { useState } from 'react';
import { useTheme } from '../themeStore';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';
const n=(v:any)=>parseFloat(v)||0;

export default function PriceTrackerScreen(){
  const { colors: C } = useTheme();
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
  const trendIcon=stats.trend==='up'?'📈':stats.trend==='down'?'📉':'➡️';
  const trendColor=stats.trend==='up'?C.red:stats.trend==='down'?C.green:C.text2;
  const trendText=stats.trend==='up'?'Rising':stats.trend==='down'?'Falling':'Stable';
  const stores=[...new Set(points.map((p:any)=>p.store))];
  const storeColors=[C.accent,C.accent2,C.accent3,C.gold,C.green];

  return(
    <ScrollView style={[s.scroll,{backgroundColor:C.bg}]} contentContainerStyle={s.container} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

      <View style={[s.card,{backgroundColor:C.surface,borderColor:C.border}]}>
        <View style={s.cardRow}>
          <View style={[s.cardIcon,{backgroundColor:'rgba(255,106,158,0.18)'}]}><Text>📈</Text></View>
          <Text style={[s.cardTitle,{color:C.text}]}>Price Trend Tracker</Text>
        </View>
        <Text style={[s.desc,{color:C.text2}]}>Track how prices change over time across your receipt history.</Text>

        <View style={s.inputRow}>
          <TextInput
            style={[s.input,{backgroundColor:C.surface2,borderColor:C.border,color:C.text}]}
            placeholder="e.g. milk, chicken, paprika..."
            placeholderTextColor={C.text3}
            value={input} onChangeText={setInput}
            onSubmitEditing={track} returnKeyType="search"
          />
          <TouchableOpacity style={[s.trackBtn,loading&&{opacity:0.5},{backgroundColor:C.accent2}]} onPress={track} disabled={loading} activeOpacity={0.85}>
            {loading?<ActivityIndicator color="#fff" size="small"/>:<Text style={s.trackBtnTxt}>Track</Text>}
          </TouchableOpacity>
        </View>

        {error!==''&&<View style={s.errBox}><Text style={[s.errTxt,{color:C.red}]}>⚠  {error}</Text></View>}
      </View>

      {result&&(
        <>
          <View style={s.statsGrid}>
            <View style={[s.statBox,{backgroundColor:C.surface2,borderColor:C.border}]}>
              <Text style={[s.statVal,{color:C.green}]}>${stats.lowest||'—'}</Text>
              <Text style={[s.statLbl,{color:C.text3}]}>Lowest Paid</Text>
            </View>
            <View style={[s.statBox,{backgroundColor:C.surface2,borderColor:C.border}]}>
              <Text style={[s.statVal,{color:C.red}]}>${stats.highest||'—'}</Text>
              <Text style={[s.statLbl,{color:C.text3}]}>Highest Paid</Text>
            </View>
            <View style={[s.statBox,{backgroundColor:C.surface2,borderColor:C.border}]}>
              <Text style={[s.statVal,{color:C.accent}]}>${stats.average||'—'}</Text>
              <Text style={[s.statLbl,{color:C.text3}]}>Average</Text>
            </View>
            <View style={[s.statBox,{backgroundColor:C.surface2,borderColor:C.border}]}>
              <Text style={[s.statVal,{color:trendColor}]}>{trendIcon}</Text>
              <Text style={[s.statLbl,{color:C.text3}]}>{trendText}</Text>
              <Text style={[s.statSub,{color:trendColor}]}>Now: ${stats.current||'—'}</Text>
            </View>
          </View>

          <Text style={[s.sectionTitle,{color:C.text}]}>Price History for "{itemName}"</Text>

          {stores.length>1&&(
            <View style={s.legendRow}>
              {stores.map((store,i)=>(
                <View key={i} style={s.legendItem}>
                  <View style={[s.legendDot,{backgroundColor:storeColors[i%storeColors.length]}]}/>
                  <Text style={[s.legendTxt,{color:C.text2}]}>{store}</Text>
                </View>
              ))}
            </View>
          )}

          {points.length<2?(
            <View style={[s.noDataBox,{backgroundColor:C.surface2,borderColor:C.border}]}>
              <Text style={[s.noDataTxt,{color:C.text}]}>Only one data point found.</Text>
              <Text style={[s.noDataSub,{color:C.text3}]}>Scan more receipts with this item to see price trends.</Text>
            </View>
          ):(
            <View style={[s.chartCard,{backgroundColor:C.surface2,borderColor:C.border}]}>
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
                      <Text style={[s.barDate,{color:C.text3}]} numberOfLines={1}>{(p.date||'').slice(5)}</Text>
                      <Text style={[s.barStore,{color:C.text3}]} numberOfLines={1}>{p.store?.split(' ')[0]}</Text>
                    </View>
                  );
                })}
              </View>
            </View>
          )}

          <View style={[s.historyCard,{backgroundColor:C.surface2,borderColor:C.border}]}>
            <Text style={[s.historyTitle,{color:C.text2}]}>All Purchases</Text>
            {[...points].reverse().map((p:any,i:number)=>{
              const storeIdx=stores.indexOf(p.store);
              const color=storeColors[storeIdx%storeColors.length];
              const priceLabel=p.unit&&p.unit!=='each'
                ?`$${n(p.unit_price).toFixed(2)}/${p.unit} (${p.quantity} ${p.unit} = $${n(p.price).toFixed(2)})`
                :`$${n(p.unit_price).toFixed(2)}`;
              return(
                <View key={i} style={[s.histRow,{borderBottomColor:C.border}]}>
                  <View style={{flex:1}}>
                    <Text style={[s.histItem,{color:C.text}]}>{p.item}</Text>
                    <View style={s.histMeta}>
                      <View style={[s.histDot,{backgroundColor:color}]}/>
                      <Text style={[s.histStore,{color:C.text3}]}>{p.store}</Text>
                      <Text style={[s.histDate,{color:C.text3}]}>· {p.date}</Text>
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
  scroll:{flex:1},
  container:{padding:16,paddingBottom:40},
  card:{borderRadius:20,borderWidth:1,padding:20,marginBottom:16},
  cardRow:{flexDirection:'row',alignItems:'center',gap:10,marginBottom:14},
  cardIcon:{width:30,height:30,borderRadius:9,alignItems:'center',justifyContent:'center'},
  cardTitle:{fontSize:15,fontWeight:'700'},
  desc:{fontSize:12,lineHeight:18,marginBottom:14},
  inputRow:{flexDirection:'row',gap:10,alignItems:'center'},
  input:{flex:1,borderWidth:1,borderRadius:11,padding:12,paddingHorizontal:14,fontSize:14},
  trackBtn:{borderRadius:11,paddingHorizontal:18,paddingVertical:13},
  trackBtnTxt:{color:'#fff',fontWeight:'700',fontSize:14},
  errBox:{marginTop:12,padding:12,backgroundColor:'rgba(255,107,107,0.08)',borderWidth:1,borderColor:'rgba(255,107,107,0.2)',borderRadius:10},
  errTxt:{fontSize:12},
  statsGrid:{flexDirection:'row',flexWrap:'wrap',gap:10,marginBottom:16},
  statBox:{flex:1,minWidth:'45%',borderRadius:14,padding:14,borderWidth:1,alignItems:'center'},
  statVal:{fontSize:18,fontWeight:'800',letterSpacing:-0.5,marginBottom:4},
  statLbl:{fontSize:10,textTransform:'uppercase',letterSpacing:0.5},
  statSub:{fontSize:11,marginTop:2},
  sectionTitle:{fontSize:14,fontWeight:'700',marginBottom:10},
  legendRow:{flexDirection:'row',flexWrap:'wrap',gap:10,marginBottom:12},
  legendItem:{flexDirection:'row',alignItems:'center',gap:5},
  legendDot:{width:8,height:8,borderRadius:4},
  legendTxt:{fontSize:12},
  noDataBox:{borderRadius:14,padding:24,alignItems:'center',marginBottom:14,borderWidth:1},
  noDataTxt:{fontSize:14,fontWeight:'600',marginBottom:6},
  noDataSub:{fontSize:12,textAlign:'center'},
  chartCard:{borderRadius:14,borderWidth:1,padding:16,marginBottom:14},
  timeline:{flexDirection:'row',alignItems:'flex-end',gap:8,height:160,paddingTop:30},
  barWrap:{flex:1,alignItems:'center',justifyContent:'flex-end'},
  barLabel:{fontSize:9,marginBottom:4,fontWeight:'600'},
  bar:{width:'100%',borderRadius:4,borderWidth:1,minHeight:20},
  barDate:{fontSize:8,marginTop:4,textAlign:'center'},
  barStore:{fontSize:8,textAlign:'center'},
  historyCard:{borderRadius:14,borderWidth:1,padding:16},
  historyTitle:{fontSize:11,fontWeight:'600',letterSpacing:0.5,textTransform:'uppercase',marginBottom:12},
  histRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'flex-start',paddingVertical:10,borderBottomWidth:1,gap:10},
  histItem:{fontSize:13,fontWeight:'500',marginBottom:4},
  histMeta:{flexDirection:'row',alignItems:'center',gap:5},
  histDot:{width:6,height:6,borderRadius:3},
  histStore:{fontSize:11},
  histDate:{fontSize:11},
  histPrice:{fontSize:13,fontWeight:'700'},
});
