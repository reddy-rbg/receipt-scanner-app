import { useState, useEffect } from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';
const C = {
  bg:'#080810',surface:'#0f0f1a',surface2:'#16162a',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff',accent2:'#ff6a9e',accent3:'#6affd4',
  text:'#ede8ff',text2:'#7e7a9a',text3:'#3d3a55',
  green:'#4ade80',gold:'#fbbf24',
};
const MENU=[
  {icon:'🔔',label:'Notifications',color:C.accent},
  {icon:'🔒',label:'Privacy & Security',color:C.accent2},
  {icon:'🎨',label:'Appearance',color:C.accent3},
  {icon:'❓',label:'Help & Support',color:C.gold},
  {icon:'⭐',label:'Rate ReceiptAI',color:C.green},
  {icon:'📤',label:'Share App',color:C.text2},
];
const n=(v:any)=>parseFloat(v)||0;

export default function ProfileScreen(){
  const [stats,setStats]=useState({receipts:0,spent:0,saved:0,stores:0});
  const [loading,setLoading]=useState(true);

  useEffect(()=>{
    // ✅ Web app uses: data.total_receipts, data.total_spent, data.total_saved
    fetch(`${API}/summary`)
      .then(r=>r.json())
      .then(d=>{
        setStats({
          receipts: d.total_receipts||0,
          spent:    d.total_spent||0,
          saved:    d.total_saved||0,   // ← total_saved not total_savings
          stores:   d.unique_stores||d.total_stores||0,
        });
      })
      .catch(()=>{})
      .finally(()=>setLoading(false));
  },[]);

  return(
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false}>

      <View style={s.avatarSection}>
        <View style={s.avatar}><Text style={s.avatarTxt}>✦</Text></View>
        <Text style={s.userName}>ReceiptAI User</Text>
        <Text style={s.userSub}>Johnson, AR</Text>
        <View style={s.statusBadge}>
          <View style={s.dot}/>
          <Text style={s.statusTxt}>API Connected</Text>
        </View>
      </View>

      {loading?(
        <ActivityIndicator color={C.accent} style={{marginBottom:16}}/>
      ):(
        <View style={s.grid}>
          <View style={[s.statBox,{borderBottomColor:C.accent}]}>
            <Text style={[s.statVal,{color:C.accent}]}>{stats.receipts}</Text>
            <Text style={s.statLbl}>Receipts</Text>
          </View>
          <View style={[s.statBox,{borderBottomColor:C.accent2}]}>
            <Text style={[s.statVal,{color:C.accent2}]}>${n(stats.spent).toFixed(0)}</Text>
            <Text style={s.statLbl}>Spent</Text>
          </View>
          <View style={[s.statBox,{borderBottomColor:C.accent3}]}>
            <Text style={[s.statVal,{color:C.accent3}]}>${n(stats.saved).toFixed(0)}</Text>
            <Text style={s.statLbl}>Saved</Text>
          </View>
          <View style={[s.statBox,{borderBottomColor:C.gold}]}>
            <Text style={[s.statVal,{color:C.gold}]}>{stats.stores}</Text>
            <Text style={s.statLbl}>Stores</Text>
          </View>
        </View>
      )}

      <View style={s.apiCard}>
        <Text style={s.apiLbl}>Backend API</Text>
        <Text style={s.apiUrl}>web-production-3605f4.up.railway.app</Text>
        <View style={s.apiRow}>
          <View style={s.greenDot}/>
          <Text style={s.apiStatus}>Online · Railway · FastAPI + Claude AI</Text>
        </View>
      </View>

      <View style={s.menuCard}>
        {MENU.map((item,i)=>(
          <TouchableOpacity key={i} style={[s.menuItem,i<MENU.length-1&&{borderBottomWidth:1,borderBottomColor:C.border}]} activeOpacity={0.7}>
            <View style={[s.menuIcon,{backgroundColor:item.color+'22'}]}>
              <Text style={{fontSize:16}}>{item.icon}</Text>
            </View>
            <Text style={s.menuLbl}>{item.label}</Text>
            <Text style={s.menuArrow}>›</Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={s.version}>ReceiptAI v1.0  ·  React Native + FastAPI + Claude AI</Text>
    </ScrollView>
  );
}

const s=StyleSheet.create({
  scroll:{flex:1,backgroundColor:C.bg},
  container:{padding:16,paddingBottom:40},
  avatarSection:{alignItems:'center',paddingVertical:24},
  avatar:{width:72,height:72,borderRadius:20,backgroundColor:'rgba(124,106,255,0.18)',borderWidth:2,borderColor:C.accent,alignItems:'center',justifyContent:'center',marginBottom:12},
  avatarTxt:{fontSize:28,color:C.accent},
  userName:{color:C.text,fontSize:20,fontWeight:'800',marginBottom:4,letterSpacing:-0.5},
  userSub:{color:C.text2,fontSize:13,marginBottom:10},
  statusBadge:{flexDirection:'row',alignItems:'center',gap:6,backgroundColor:'rgba(74,222,128,0.1)',borderWidth:1,borderColor:'rgba(74,222,128,0.2)',borderRadius:99,paddingHorizontal:12,paddingVertical:4},
  dot:{width:6,height:6,borderRadius:3,backgroundColor:C.green},
  statusTxt:{color:C.green,fontSize:12},
  grid:{flexDirection:'row',gap:10,marginBottom:16},
  statBox:{flex:1,backgroundColor:C.surface2,borderRadius:14,padding:12,borderWidth:1,borderColor:C.border,borderBottomWidth:2,alignItems:'center'},
  statVal:{fontSize:18,fontWeight:'800',letterSpacing:-0.5,marginBottom:4},
  statLbl:{color:C.text3,fontSize:9,textTransform:'uppercase',letterSpacing:0.5},
  apiCard:{backgroundColor:C.surface,borderRadius:16,borderWidth:1,borderColor:C.border,padding:16,marginBottom:16},
  apiLbl:{color:C.text3,fontSize:10,textTransform:'uppercase',letterSpacing:0.8,marginBottom:6},
  apiUrl:{color:C.accent,fontSize:12,fontFamily:'monospace',marginBottom:8},
  apiRow:{flexDirection:'row',alignItems:'center',gap:6},
  greenDot:{width:6,height:6,borderRadius:3,backgroundColor:C.green},
  apiStatus:{color:C.text2,fontSize:12},
  menuCard:{backgroundColor:C.surface,borderRadius:18,borderWidth:1,borderColor:C.border,overflow:'hidden',marginBottom:20},
  menuItem:{flexDirection:'row',alignItems:'center',padding:16,gap:12},
  menuIcon:{width:36,height:36,borderRadius:10,alignItems:'center',justifyContent:'center'},
  menuLbl:{flex:1,color:C.text,fontSize:14,fontWeight:'500'},
  menuArrow:{color:C.text3,fontSize:22},
  version:{color:C.text3,fontSize:11,textAlign:'center',letterSpacing:0.3},
});
