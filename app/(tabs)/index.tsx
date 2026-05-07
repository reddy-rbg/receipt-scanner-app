import { useState, useEffect } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, Image,
  StyleSheet, ActivityIndicator, Alert,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';

const API = 'https://web-production-3605f4.up.railway.app';
const C = {
  bg:'#080810',surface:'#0f0f1a',surface2:'#16162a',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff',accent2:'#ff6a9e',accent3:'#6affd4',
  text:'#ede8ff',text2:'#7e7a9a',text3:'#3d3a55',
  green:'#4ade80',red:'#ff6b6b',
};
function mime(uri:string){
  const e=uri.split('.').pop()?.toLowerCase();
  if(e==='png') return 'image/png';
  if(e==='webp') return 'image/webp';
  if(e==='heic') return 'image/heic';
  return 'image/jpeg';
}
const n=(v:any)=>parseFloat(v)||0;

export default function ScanScreen(){
  const [uri,setUri]=useState<string|null>(null);
  const [loading,setLoading]=useState(false);
  const [result,setResult]=useState<any>(null);
  const [duplicate,setDuplicate]=useState('');
  const [stats,setStats]=useState({receipts:0,spent:0,saved:0});

  useEffect(()=>{loadStats();},[]);

  async function loadStats(){
    try{
      const res=await fetch(`${API}/summary`);
      const d=await res.json();
      // web app uses: data.total_receipts, data.total_spent, data.total_saved
      setStats({
        receipts: d.total_receipts||0,
        spent:    d.total_spent||0,
        saved:    d.total_saved||0,
      });
    }catch{}
  }

  async function pickImage(){
    const p=await ImagePicker.requestMediaLibraryPermissionsAsync();
    if(!p.granted){Alert.alert('Permission needed','Allow photo access.');return;}
    const r=await ImagePicker.launchImageLibraryAsync({mediaTypes:ImagePicker.MediaTypeOptions.Images,quality:0.85});
    if(!r.canceled&&r.assets[0]){setUri(r.assets[0].uri);setResult(null);setDuplicate('');}
  }

  async function takePhoto(){
    const p=await ImagePicker.requestCameraPermissionsAsync();
    if(!p.granted){Alert.alert('Permission needed','Allow camera access.');return;}
    const r=await ImagePicker.launchCameraAsync({quality:0.85});
    if(!r.canceled&&r.assets[0]){setUri(r.assets[0].uri);setResult(null);setDuplicate('');}
  }

  async function scan(){
    if(!uri) return;
    setLoading(true);setResult(null);setDuplicate('');
    try{
      const fd=new FormData();
      fd.append('file',{uri,name:uri.split('/').pop()||'receipt.jpg',type:mime(uri)} as any);
      const res=await fetch(`${API}/scan-receipt`,{method:'POST',body:fd,headers:{'Content-Type':'multipart/form-data'}});
      const data=await res.json();
      if(!res.ok){Alert.alert('Scan Failed',data.detail||`Error ${res.status}`);return;}
      // ✅ Backend returns { receipt: {...}, duplicate: bool, message: string }
      if(data.duplicate) setDuplicate(data.message||'Duplicate receipt detected.');
      setResult(data.receipt); // <-- KEY FIX: use data.receipt not data
      loadStats();
    }catch(e:any){
      Alert.alert('Error',e.message||'Could not connect. Try again.');
    }finally{setLoading(false);}
  }

  return(
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false}>

      {/* STATS */}
      <View style={s.statsRow}>
        <View style={[s.statBox,{borderBottomColor:C.accent}]}>
          <Text style={s.statLabel}>Receipts</Text>
          <Text style={[s.statVal,{color:C.accent}]}>{stats.receipts}</Text>
        </View>
        <View style={[s.statBox,{borderBottomColor:C.accent2}]}>
          <Text style={s.statLabel}>Spent</Text>
          <Text style={[s.statVal,{color:C.accent2}]}>${n(stats.spent).toFixed(0)}</Text>
        </View>
        <View style={[s.statBox,{borderBottomColor:C.accent3}]}>
          <Text style={s.statLabel}>Saved</Text>
          <Text style={[s.statVal,{color:C.accent3}]}>${n(stats.saved).toFixed(0)}</Text>
        </View>
      </View>

      {/* SCAN CARD */}
      <View style={s.card}>
        <View style={s.cardRow}>
          <View style={[s.cardIcon,{backgroundColor:'rgba(124,106,255,0.18)'}]}><Text>📷</Text></View>
          <Text style={s.cardTitle}>Scan Receipt</Text>
        </View>

        <TouchableOpacity style={s.uploadZone} onPress={pickImage} activeOpacity={0.8}>
          <Text style={s.uploadEmoji}>📄</Text>
          <Text style={s.uploadTitle}>Tap to select a receipt</Text>
          <Text style={s.uploadSub}>JPG · PNG · WEBP</Text>
          <View style={s.fmtRow}>
            {['JPG','PNG','WEBP'].map(f=>(
              <View key={f} style={s.fmtPill}><Text style={s.fmtText}>{f}</Text></View>
            ))}
          </View>
        </TouchableOpacity>

        {uri&&<Image source={{uri}} style={s.preview} resizeMode="contain"/>}

        <View style={s.btnRow}>
          <TouchableOpacity style={[s.btn,s.btnSec,{flex:1}]} onPress={pickImage} activeOpacity={0.8}>
            <Text style={s.btnSecTxt}>📁  Gallery</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[s.btn,s.btnSec,{flex:1}]} onPress={takePhoto} activeOpacity={0.8}>
            <Text style={s.btnSecTxt}>📸  Camera</Text>
          </TouchableOpacity>
        </View>

        {uri&&(
          <TouchableOpacity style={[s.btn,s.btnPri,loading&&{opacity:0.5}]} onPress={scan} disabled={loading} activeOpacity={0.85}>
            {loading?<ActivityIndicator color="#fff" size="small"/>:<Text style={s.btnPriTxt}>✦  Scan Receipt</Text>}
          </TouchableOpacity>
        )}
      </View>

      {/* DUPLICATE WARNING */}
      {duplicate!==''&&(
        <View style={s.warnBox}>
          <Text style={s.warnText}>⚠  {duplicate}</Text>
        </View>
      )}

      {/* RESULT - uses r.store, r.date, r.items, r.total etc from data.receipt */}
      {result&&(
        <View style={s.resultCard}>
          <View style={s.resultHeader}>
            <Text style={s.resultStore}>{result.store||'Unknown Store'}</Text>
            <Text style={s.resultMeta}>
              {[result.date&&`📅 ${result.date}${result.time?' '+result.time:''}`,result.address&&`📍 ${result.address}`].filter(Boolean).join('  ·  ')}
            </Text>
          </View>

          <View style={s.items}>
            {(result.items||[]).map((item:any,i:number)=>{
              const neg  = item.price < 0;
              const ps   = neg ? `-$${Math.abs(item.price).toFixed(2)}` : `$${n(item.price).toFixed(2)}`;
              const unit = (item.unit||'').toLowerCase().trim();
              const qty  = n(item.quantity) || 1;
              const up   = n(item.unit_price);

              // All known weighted/volume units
              const UNITS = ['lb','lbs','oz','kg','g','mg','ml','l','liter','liters',
                             'fl oz','fl','gal','gallon','pt','pint','qt','quart','ct','count'];
              const isWeighted = UNITS.includes(unit);

              let qtyLabel  = '';
              let unitLabel = '';

              if (isWeighted && unit && unit !== 'each') {
                qtyLabel  = `${qty} ${unit}`;
                if (up > 0) unitLabel = `@ $${up.toFixed(2)}/${unit}`;
              } else if (qty > 1) {
                qtyLabel  = `×${qty}`;
                if (up > 0) unitLabel = `@ $${up.toFixed(2)} each`;
              }

              return (
                <View key={i} style={s.itemRow}>
                  <View style={{flex:1}}>
                    {item.code ? <Text style={s.itemCode}>{item.code}</Text> : null}
                    <View style={{flexDirection:'row',alignItems:'center',flexWrap:'wrap',gap:4}}>
                      <Text style={s.itemName}>{item.name}</Text>
                      {qtyLabel ? <Text style={s.itemQty}>{qtyLabel}</Text> : null}
                    </View>
                    {unitLabel ? <Text style={s.itemUnit}>{unitLabel}</Text> : null}
                  </View>
                  <Text style={[s.itemPrice,{color:neg?C.green:C.text}]}>{ps}</Text>
                </View>
              );
            })}
          </View>

          <View style={s.totals}>
            {n(result.subtotal)>0&&<View style={s.tRow}><Text style={s.tLbl}>Subtotal</Text><Text style={s.tVal}>${n(result.subtotal).toFixed(2)}</Text></View>}
            {n(result.discount)>0&&<View style={s.tRow}><Text style={s.tLbl}>Discount</Text><Text style={[s.tVal,{color:C.green}]}>-${n(result.discount).toFixed(2)}</Text></View>}
            {n(result.tax)>0&&<View style={s.tRow}><Text style={s.tLbl}>Tax</Text><Text style={s.tVal}>${n(result.tax).toFixed(2)}</Text></View>}
            <View style={[s.tRow,s.tFinal]}>
              <Text style={s.tFinalLbl}>Total Paid</Text>
              <Text style={s.tFinalAmt}>${n(result.total).toFixed(2)}</Text>
            </View>
          </View>

          {n(result.total_savings)>0&&(
            <View style={s.savingsBanner}>
              <Text style={s.savingsText}>🎉  You saved ${n(result.total_savings).toFixed(2)} on this trip!</Text>
            </View>
          )}

          <TouchableOpacity style={[s.btn,s.btnSec,{margin:16,marginTop:12}]} onPress={()=>{setResult(null);setUri(null);setDuplicate('');}}>
            <Text style={s.btnSecTxt}>↩  Scan Another Receipt</Text>
          </TouchableOpacity>
        </View>
      )}
    </ScrollView>
  );
}

const s=StyleSheet.create({
  scroll:{flex:1,backgroundColor:C.bg},
  container:{padding:16,paddingBottom:40},
  statsRow:{flexDirection:'row',gap:10,marginBottom:16},
  statBox:{flex:1,backgroundColor:C.surface2,borderRadius:14,padding:14,borderWidth:1,borderColor:C.border,borderBottomWidth:2},
  statLabel:{fontSize:10,color:C.text3,textTransform:'uppercase',letterSpacing:0.6,marginBottom:4},
  statVal:{fontSize:22,fontWeight:'800',letterSpacing:-0.5},
  card:{backgroundColor:C.surface,borderRadius:20,borderWidth:1,borderColor:C.border,padding:20,marginBottom:16},
  cardRow:{flexDirection:'row',alignItems:'center',gap:10,marginBottom:16},
  cardIcon:{width:30,height:30,borderRadius:9,alignItems:'center',justifyContent:'center'},
  cardTitle:{color:C.text,fontSize:15,fontWeight:'700'},
  uploadZone:{borderWidth:1.5,borderColor:'rgba(124,106,255,0.3)',borderStyle:'dashed',borderRadius:14,padding:28,alignItems:'center',backgroundColor:'rgba(124,106,255,0.03)'},
  uploadEmoji:{fontSize:34,marginBottom:8},
  uploadTitle:{color:C.text,fontSize:14,fontWeight:'600',marginBottom:4},
  uploadSub:{color:C.text2,fontSize:12,marginBottom:10},
  fmtRow:{flexDirection:'row',gap:6},
  fmtPill:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:99,paddingHorizontal:8,paddingVertical:2},
  fmtText:{color:C.text3,fontSize:10},
  preview:{width:'100%',height:200,borderRadius:12,marginTop:14,borderWidth:1,borderColor:C.border},
  btnRow:{flexDirection:'row',gap:10,marginTop:12},
  btn:{borderRadius:12,padding:14,alignItems:'center',marginTop:10},
  btnPri:{backgroundColor:C.accent,shadowColor:C.accent,shadowOpacity:0.4,shadowRadius:12},
  btnPriTxt:{color:'#fff',fontSize:15,fontWeight:'600'},
  btnSec:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border},
  btnSecTxt:{color:C.text,fontSize:13,fontWeight:'500'},
  warnBox:{backgroundColor:'rgba(251,191,36,0.08)',borderWidth:1,borderColor:'rgba(251,191,36,0.25)',borderRadius:12,padding:14,marginBottom:12},
  warnText:{color:'#fbbf24',fontSize:13},
  resultCard:{backgroundColor:C.surface2,borderRadius:18,overflow:'hidden',borderWidth:1,borderColor:'rgba(106,255,212,0.2)',marginBottom:16},
  resultHeader:{padding:16,backgroundColor:'rgba(106,255,212,0.05)',borderBottomWidth:1,borderBottomColor:'rgba(106,255,212,0.15)'},
  resultStore:{color:C.text,fontSize:18,fontWeight:'800',letterSpacing:-0.5},
  resultMeta:{color:C.text2,fontSize:11,marginTop:3},
  items:{padding:16},
  itemRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'flex-start',paddingVertical:7,borderBottomWidth:1,borderBottomColor:C.border,gap:10},
  itemCode:{color:C.text3,fontSize:9,fontFamily:'monospace'},
  itemName:{color:C.text,fontSize:13},
  itemQty:{color:C.accent,fontSize:11},
  itemUnit:{color:C.text2,fontSize:11,marginTop:2},
  itemPrice:{fontSize:13,fontWeight:'600'},
  totals:{backgroundColor:C.surface,margin:16,borderRadius:12,padding:14},
  tRow:{flexDirection:'row',justifyContent:'space-between',paddingVertical:4},
  tLbl:{color:C.text2,fontSize:13},
  tVal:{color:C.text,fontSize:13,fontWeight:'500'},
  tFinal:{borderTopWidth:1,borderTopColor:C.border,marginTop:6,paddingTop:10},
  tFinalLbl:{color:C.text,fontSize:15,fontWeight:'700'},
  tFinalAmt:{color:C.accent,fontSize:15,fontWeight:'800'},
  savingsBanner:{marginHorizontal:16,marginBottom:8,padding:10,backgroundColor:'rgba(74,222,128,0.1)',borderWidth:1,borderColor:'rgba(74,222,128,0.25)',borderRadius:10},
  savingsText:{color:C.green,fontWeight:'600',fontSize:13,textAlign:'center'},
});
