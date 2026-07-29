# 固定深度 BranchUnit 程序生成方法

## 1. 方法定位

当前生成方法准确地说是：

> 固定深度、角色模板约束、种子驱动的层级 BranchUnit 程序生成。

它不是递归生长，也不是完全自由的随机生成。方法固定 7 条一级枝、12 条二级枝和 2 条三级枝的拓扑；在固定合法范围内，由 seed 改变挂载位置、方向、长度、开口角、控制柄和弯曲模式。

本文对应当前结果目录：

- **artifacts/runs/_scratch_whole_local_true_lateral_n12_v23**

需要注意，**v23** 只是运行结果目录的版本标签，不是算法内核版本。当前源代码中的真实标识为：

- **GEOMETRY_KERNEL_ID = whole_local_true_lateral_branch_units_n12_v17**
- **PLAN_ID = proto_sw_1_3_J0c_true_lateral_units_7_12_2_v21**

主要实现位于：

- [whole_local_branch.py](./whole_local_branch.py)
- [run_whole_local_n12_dev.py](./run_whole_local_n12_dev.py)
- [WHOLE_LOCAL_N12_DEV_PROTOCOL.md](./WHOLE_LOCAL_N12_DEV_PROTOCOL.md)

---

## 2. 总体生成流程

完整过程可以写成：

\[
P_0=\operatorname{strip\_profile}(\text{prototype})
\]

\[
G=\operatorname{plan\_j0a}(P_0,z)
\]

\[
C=\operatorname{compile\_plan}(G,P_0)
\]

\[
R=\operatorname{validate\_result}(P_0,C)
\]

其中：

- \(P_0\) 是从原型中提取的严格输入；
- \(z\) 是 seed；
- \(G\) 是一次性生成的全局层级计划；
- \(C\) 是编译后的全部曲线；
- \(R\) 是只读验证结果。

流程如下：

~~~text
主干、两个花位和画幅
          ↓
确定全局上下边缘带和边缘槽位
          ↓
规划 7 个固定深度 BranchUnit
          ↓
生成 7 条 L1
          ↓
在指定 L1 上生成 12 条 L2
          ↓
在指定 L2 上生成 2 条 L3
          ↓
执行结构、边缘、曲率、间距和 seed 变化验证
          ↓
输出记录图、调试图、Unit 图和证明文件
~~~

每个 seed 只生成一个候选。当前方法没有候选搜索、重试、补抽、自动修复或验证反馈驱动的几何修改。

---

## 3. 严格输入 \(P_0\)

生成器只消费：

\[
P_0=
\left(
B(s),
\{E_1,E_2\},
[x_0,x_1],
W,H
\right)
\]

其中：

- \(B(s)\) 是主干；
- \(s\in[0,1]\) 是主干的归一化弧长；
- \(E_1,E_2\) 是两个椭圆花位；
- \([x_0,x_1]\) 是重复单元范围；
- \(W,H\) 是原始画布尺寸。

当前实验要求：

\[
W=1024,\qquad H=304
\]

\[
[x_0,x_1]=[0,256]
\]

因此，原始画布为 \(1024\times304\)，但当前分支生成和验证针对宽度为 256 的一个可见重复单元。

主干由一组弧长采样表示：

\[
B=
\left\{
(s_k,\mathbf p_k,\mathbf t_k)
\right\}_{k=1}^{N}
\]

其中 \(\mathbf p_k\) 是主干点，\(\mathbf t_k\) 是对应单位切向。

花位表示为：

\[
E_f=(\mathbf c_f,r^x_f,r^y_f)
\]

其中 \(\mathbf c_f\) 是花心，\(r^x_f,r^y_f\) 是椭圆半径。

旧 SVG 中的已有分支、引导线、growth region、attachment、branch role、clearance 和 QA 字段不会进入 \(P_0\)。当前分支完全由程序重新生成。

---

## 4. 固定深度 BranchUnit 拓扑

定义第 \(i\) 个枝组为：

\[
U_i=
\left\{
P_i,
\{S_{ij}\},
\{T_{ijk}\}
\right\}
\]

其中：

- \(P_i\) 是一级枝 L1；
- \(S_{ij}\) 是挂在 \(P_i\) 上的二级枝 L2；
- \(T_{ijk}\) 是挂在某条 \(S_{ij}\) 上的三级枝 L3。

当前拓扑固定为：

\[
N_1=7,\qquad N_2=12,\qquad N_3=2
\]

具体父子关系为：

~~~text
primary_1 ─ secondary_1a, secondary_1b

primary_2 ─ secondary_2a, secondary_2b

primary_3 ─ secondary_3a ─ tertiary_3a_1
          └ secondary_3b

primary_4 ─ secondary_4a

primary_5 ─ secondary_5a

primary_6 ─ secondary_6a ─ tertiary_6a_1
          └ secondary_6b

primary_7 ─ secondary_7a, secondary_7b
~~~

各 Unit 的整体责任如下：

| Unit | 一级枝目标 | L2 数量 | L3 数量 | 整体责任 |
|---|---|---:|---:|---|
| \(U_1\) | 上边缘 | 2 | 0 | L1 抵达上边缘 |
| \(U_2\) | 内部目标 | 2 | 0 | 一条 L2 抵达下边缘 |
| \(U_3\) | 下边缘 | 2 | 1 | L1 抵达下边缘 |
| \(U_4\) | 花位 1 | 1 | 0 | 承托花位 1 |
| \(U_5\) | 花位 2 | 1 | 0 | 承托花位 2 |
| \(U_6\) | 上边缘 | 2 | 1 | L1 抵达上边缘 |
| \(U_7\) | 内部目标 | 2 | 0 | 一条 L2 抵达上边缘 |

五个非花位 Unit 均有一条由层级结构形成的路径抵达上边缘或下边缘。该约束不是要求每一条子枝都抵达边缘。

编译顺序固定为：

\[
L1\rightarrow L2\rightarrow L3
\]

代码中直接遍历层级 2 和 3，不存在递归调用、动态 STOP 判断或动态深度决定。

---

## 5. seed 到参数的确定性映射

### 5.1 基础哈希坐标

将 seed \(z\) 和参数标签 \(\ell\) 映射到 \([0,1]\)：

\[
U(z,\ell)=
\frac{
\operatorname{int}_{64}
\left[
\operatorname{SHA256}(z\Vert\ell)_{0:8}
\right]
}{
2^{64}-1
}
\]

同一 seed 和同一标签会得到完全相同的数值，因此结果可以精确重放。

### 5.2 可见变化坐标

为了使相邻 seed 产生更明显的几何变化，定义：

\[
V(z,\ell)=
\left(
0.6180339887498949\,z+
U(0,\text{visible.}\Vert\ell)
\right)\bmod1
\]

其中 \(0.6180339887498949\) 为黄金比例相关步长。

所有区间采样统一写成：

\[
\operatorname{lerp}(a,b,u)=a+(b-a)u
\]

因此一个参数通常表示为：

\[
p=
\operatorname{lerp}
\left(
p_{\min},
p_{\max},
V(z,\ell)
\right)
\]

### 5.3 挂载位置的三状态变化

挂载位置没有采用完全自由的连续随机，而是采用标签专属的低、中、高三状态：

\[
q_i(z)=\Pi_i[z\bmod3]
\]

其中 \(\Pi_i\) 是由标签决定的三状态排列。

实际坐标为：

\[
m_i=M_{i,q_i(z)}+\epsilon_i
\]

\[
\epsilon_i=
\operatorname{lerp}
\left(
\epsilon_{\min},
\epsilon_{\max},
U(z,\ell_i^{\text{jitter}})
\right)
\]

这样，连续三个 seed 会让同一挂载角色覆盖低、中、高三个位置，但不同角色不会完全同步移动。

---

## 6. 全局上下边缘带

当前严格边缘只包括上边缘和下边缘。左右边缘用于 repeat，不设置严格抵达要求。

上边缘带位置：

\[
Y_T=
\operatorname{lerp}
\left(
38,52,V(z,\ell_T)
\right)
\]

下边缘带位置：

\[
Y_B=
H-
\operatorname{lerp}
\left(
12,22,V(z,\ell_B)
\right)
\]

边缘槽位也由 seed 生成：

\[
X_{1T}\in[25,80]
\]

\[
X_{6T}\in[105,155]
\]

\[
X_{7T}^{L2}\in[180,200]
\]

\[
X_{2B}^{L2}\in[42,58]
\]

\[
X_{3B}\in[70,130]
\]

它们分别对应：

- \(U_1\) 的 L1 上边缘槽位；
- \(U_6\) 的 L1 上边缘槽位；
- \(U_7\) 的 L2 上边缘槽位；
- \(U_2\) 的 L2 下边缘槽位；
- \(U_3\) 的 L1 下边缘槽位。

因此全局边缘责任为：

\[
N_{\text{top}}=3,\qquad N_{\text{bottom}}=2
\]

这些槽位将不同 Unit 的边缘终点分开，避免所有枝条在同一位置汇聚。

---

## 7. 一级枝 L1 生成

### 7.1 一级枝挂载位置

对于采用三状态挂载的一级枝：

\[
s_i=
\operatorname{clip}_{[a_i,b_i]}
\left(
S_{i,q_i(z)}
+\epsilon_i
+\Delta_r w_i
\right)
\]

其中：

- \([a_i,b_i]\) 是该一级枝的合法挂载范围；
- \(S_{i,q_i(z)}\) 是三状态基准位置；
- \(\epsilon_i\in[-0.0015,0.0015]\) 是小扰动；
- \(\Delta_r\) 是外部 **rhythm_shift**；
- \(w_i\) 是每个角色不同的节奏权重。

默认：

\[
\Delta_r=0
\]

波谷花位枝 **primary_4_flower_1** 不使用三状态表，而是在窄带内连续采样：

\[
s_4\in[0.392,0.408]
\]

它不受 **rhythm_shift** 影响，并由验证器限制在 \(0.4\pm0.01\) 内。因此它是窄带波谷锚点，而不是绝对固定点。

### 7.2 主干根点和切向

在主干归一化弧长 \(s_i\) 处采样：

\[
(\mathbf R_i,\mathbf T_i)
=
\operatorname{SampleArc}
\left(
B,s_i
\right)
\]

其中：

- \(\mathbf R_i\) 是一级枝根点；
- \(\mathbf T_i\) 是主干局部单位切向。

### 7.3 非花位一级枝目标

五条非花位一级枝使用预先分配的目标点：

\[
\mathbf E_1=
\left(
X_{1T},
Y_T+\frac{w_1}{2}
\right)
\]

\[
\mathbf E_2=(X_2,Y_2)
\]

\[
\mathbf E_3=
\left(
X_{3B},
Y_B-\frac{w_1}{2}
\right)
\]

\[
\mathbf E_6=
\left(
X_{6T},
Y_T+\frac{w_1}{2}
\right)
\]

\[
\mathbf E_7=(X_7,Y_7)
\]

其中：

\[
w_1=3.0
\]

\(\mathbf E_1,\mathbf E_3,\mathbf E_6\) 是注册边缘目标；\(\mathbf E_2,\mathbf E_7\) 是内部平衡目标。

### 7.4 花位一级枝目标

花位枝不直接连接花心，而是连接根点到花心射线与花位椭圆的交点。

设：

- 一级枝根点为 \(\mathbf R\)；
- 花心为 \(\mathbf F\)；
- 花位椭圆半径为 \((r_x,r_y)\)。

定义：

\[
\Delta=\mathbf R-\mathbf F
\]

\[
\lambda=
\sqrt{
\left(
\frac{\Delta_x}{r_x}
\right)^2+
\left(
\frac{\Delta_y}{r_y}
\right)^2
}
\]

花位轮廓目标点为：

\[
\mathbf E_f=
\mathbf F+
\frac{\Delta}{\lambda}
\]

这样可以保证：

\[
\left(
\frac{E_{f,x}-F_x}{r_x}
\right)^2+
\left(
\frac{E_{f,y}-F_y}{r_y}
\right)^2
=1
\]

一级枝在花位轮廓处结束，出口方向指向花心：

\[
\mathbf T^{out}
=
\frac{
\mathbf F-\mathbf E_f
}{
\|\mathbf F-\mathbf E_f\|
}
\]

### 7.5 一级枝开口角

目标方向为：

\[
\mathbf D_i=
\frac{
\mathbf E_i-\mathbf R_i
}{
\|\mathbf E_i-\mathbf R_i\|
}
\]

主干切向与目标方向的有符号夹角为：

\[
\delta_i=
\operatorname{atan2}
\left(
\mathbf T_i\times\mathbf D_i,
\mathbf T_i\cdot\mathbf D_i
\right)
\]

将 seed 变化与目标几何共同用于开口角：

\[
u_i^{open}
=
0.55V(z,i.\text{opening})
+
0.45
\min
\left(
1,
\frac{|\delta_i|}{120^\circ}
\right)
\]

\[
\alpha_i=
\operatorname{lerp}
\left(
\alpha_i^{\min},
\alpha_i^{\max},
u_i^{open}
\right)
\]

入口切向为：

\[
\mathbf T_i^{in}
=
R_{\sigma_i\alpha_i}\mathbf T_i
\]

其中 \(R_\theta\) 表示旋转 \(\theta\)，\(\sigma_i\in\{-1,+1\}\) 表示一级枝生长侧。

五条非花位一级枝使用固定侧序：

\[
(\sigma_1,\sigma_2,\sigma_3,\sigma_6,\sigma_7)
=
(-1,+1,+1,-1,-1)
\]

两条花位枝根据主干切向与目标方向的叉积符号决定生长侧。

---

## 8. 二级枝与三级枝生成

### 8.1 在父枝上定位根点

设父曲线为 \(P\)，子枝挂载比例为 \(m\)：

\[
(\mathbf R,\boldsymbol\tau)
=
\operatorname{SampleArc}(P,m)
\]

其中：

- \(\mathbf R\) 是子枝根点；
- \(\boldsymbol\tau\) 是父枝在该位置的局部切向；
- \(m\) 是父曲线的归一化弧长比例，不是 Bézier 参数 \(t\)。

父曲线先被采样为折线，再按累计折线长度定位根点和切向。

### 8.2 双子枝 Unit 的协调挂载

对于具有两条 L2 的 Unit，先生成一个中心位置：

\[
c_i=
C_{i,q_i(z)}
+
\operatorname{lerp}
\left(
-0.008,
0.008,
U(z,\ell_i^{jitter})
\right)
\]

再将两条子枝放置为：

\[
m_{\text{near}}=c_i-0.10
\]

\[
m_{\text{far}}=c_i+0.10
\]

因此同一 Unit 中两条 L2 的挂载间距固定为：

\[
|m_{\text{far}}-m_{\text{near}}|=0.20
\]

当前中心状态表为：

| Unit | 中心状态 |
|---|---|
| \(U_1\) | \((0.40,0.50,0.60)\) |
| \(U_2\) | \((0.45,0.52,0.59)\) |
| \(U_3\) | \((0.45,0.56,0.61)\) |
| \(U_6\) | \((0.48,0.52,0.61)\) |
| \(U_7\) | \((0.55,0.60,0.65)\) |

### 8.3 花位单子枝挂载

两个花位 Unit 各有一条 L2：

\[
m=
(0.57,0.67,0.77)_{q_i(z)}
+\epsilon
\]

\[
\epsilon\in[-0.005,0.005]
\]

### 8.4 三级枝挂载

两条 L3 分别挂在 **secondary_3a** 和 **secondary_6a** 上：

\[
m=
(0.45,0.56,0.67)_{q_i(z)}
+\epsilon
\]

\[
\epsilon\in[-0.005,0.005]
\]

当前 14 条后代曲线全部由上述 coordinated mount 赋值。因此代码中的角色 mount range 当前主要用于登记和验证，不是实际挂载值的直接采样公式。

### 8.5 子枝开口角

设子树外部控制量为：

\[
f\in[-1,1]
\]

默认：

\[
f=0
\]

子枝开口角：

\[
\omega=
\operatorname{lerp}
\left(
\omega_{\min},
\omega_{\max},
V(z,id.\text{opening})
\right)
(1+0.06f)
\]

### 8.6 自由子枝方向

自由子枝的行进角度为：

\[
\phi=
\operatorname{lerp}
\left(
\phi_{\min},
\phi_{\max},
V(z,id.\text{travel\_angle})
\right)
\]

行进方向：

\[
\mathbf D=(\cos\phi,\sin\phi)
\]

长度：

\[
L=
\operatorname{lerp}
\left(
L_{\min},
L_{\max},
V(z,id.\text{length})
\right)
\lambda_L(1+0.10f)
\]

其中 \(\lambda_L\) 是外部 **length_scale**，默认：

\[
\lambda_L=1
\]

终点为：

\[
\mathbf E=\mathbf R+L\mathbf D
\]

当前实现中，\(\phi\) 是画布全局角度，不是相对父切向的局部角度。

因此当前子枝控制具有以下性质：

- 根点由父曲线决定；
- 入口切向由父曲线局部切向决定；
- 总体 chord 方向仍由固定角色的全局角度区间决定。

所以它属于“半局部 BranchUnit 控制”，还不是完整的父局部坐标生成。

### 8.7 parent-local 入口切向

父切向和目标方向之间的有符号角为：

\[
\theta=
\operatorname{atan2}
\left(
\boldsymbol\tau\times\mathbf D,
\boldsymbol\tau\cdot\mathbf D
\right)
\]

定义：

\[
\sigma=
\begin{cases}
+1,&\theta\ge0\\
-1,&\theta<0
\end{cases}
\]

子枝入口切向为：

\[
\mathbf T^{in}
=
R_{\sigma\omega}\boldsymbol\tau
\]

因此二级枝和三级枝在根部形成真实的侧向分叉，而不是父枝的连续延长。

### 8.8 出口释放角和 C/S 模式

定义混合弯曲变量：

\[
b=
0.35U(z,\text{global.bend})
+
0.65V(z,id.\text{bend})
\]

出口释放角：

\[
\rho=
\operatorname{lerp}
\left(
18^\circ,
34^\circ,
b
\right)
\]

若模式为 C：

\[
\mathbf T^{out}
=
R_{+\rho}\mathbf D
\]

若模式为 S：

\[
\mathbf T^{out}
=
R_{-\rho}\mathbf D
\]

模式选择为：

\[
\text{mode}=
\begin{cases}
C,&V(z,id.\text{mode})<0.55\\
S,&\text{otherwise}
\end{cases}
\]

---

## 9. 边缘目标枝

当前只有两条后代曲线承担边缘目标：

- **secondary_2a** 抵达下边缘；
- **secondary_7a** 抵达上边缘。

其终点分别为：

\[
\mathbf E_{2a}
=
\left(
X_{2B}^{L2},
Y_B-\frac{w_2}{2}
\right)
\]

\[
\mathbf E_{7a}
=
\left(
X_{7T}^{L2},
Y_T+\frac{w_2}{2}
\right)
\]

其中：

\[
w_2=2.1
\]

两条边缘子枝的终端切向均为：

\[
\mathbf T^{out}=(1,0)
\]

一级边缘枝的终端切向也被设为水平的 \((\pm1,0)\)。

因此边缘目标具有两个约束：

1. 中心线终点按半线宽内缩，使可见线宽外轮廓统一接触边缘带；
2. 终端切向与边缘平行，使枝条在接近边缘时停止外冲并沿边缘略微弯曲。

左右边缘是 repeat seam，不参与这种严格 frontier 分配。

---

## 10. Bézier 曲线构造

### 10.1 三次 Bézier

三次 Bézier 的标准形式为：

\[
\mathbf B(t)=
(1-t)^3\mathbf P_0
+3(1-t)^2t\mathbf P_1
+3(1-t)t^2\mathbf P_2
+t^3\mathbf P_3
\]

\[
t\in[0,1]
\]

### 10.2 控制点

设：

- 根点为 \(\mathbf R\)；
- 终点为 \(\mathbf E\)；
- 实际根尖弦长为 \(D=\|\mathbf E-\mathbf R\|\)；
- 入口切向为 \(\mathbf T^{in}\)；
- 出口切向为 \(\mathbf T^{out}\)；
- 起始臂比例为 \(a\)；
- 末端臂比例为 \(b\)。

则：

\[
\mathbf Q_1=
\mathbf R+aD\mathbf T^{in}
\]

\[
\mathbf Q_2=
\mathbf E-bD\mathbf T^{out}
\]

### 10.3 非花位一级枝

五条非花位一级枝均具有明确目标点和终端切向，使用单段三次 Bézier：

\[
[
\mathbf R,
\mathbf Q_1,
\mathbf Q_2,
\mathbf E
]
\]

### 10.4 花位一级枝和所有 L2/L3

花位一级枝及所有二级、三级枝使用两段由二次 Bézier 升阶得到的三次 Bézier。

首先定义中间点：

\[
\mathbf M=
\frac{
\mathbf Q_1+\mathbf Q_2
}{2}
\]

第一段由二次控制点 \((\mathbf R,\mathbf Q_1,\mathbf M)\) 升阶：

\[
\left[
\mathbf R,
\mathbf R+\frac23(\mathbf Q_1-\mathbf R),
\mathbf M+\frac23(\mathbf Q_1-\mathbf M),
\mathbf M
\right]
\]

第二段由二次控制点 \((\mathbf M,\mathbf Q_2,\mathbf E)\) 升阶：

\[
\left[
\mathbf M,
\mathbf M+\frac23(\mathbf Q_2-\mathbf M),
\mathbf E+\frac23(\mathbf Q_2-\mathbf E),
\mathbf E
\right]
\]

由于：

\[
\mathbf M=
\frac{\mathbf Q_1+\mathbf Q_2}{2}
\]

第一段在 \(\mathbf M\) 处的末端导数方向与第二段在 \(\mathbf M\) 处的起始导数方向一致，因此两段自动满足 \(C^1\) 连续。

### 10.5 层级线宽

当前线宽为：

\[
w_1=3.0
\]

\[
w_2=2.1
\]

\[
w_3=1.45
\]

对应一级、二级、三级枝逐级变细。

---

## 11. 曲率与弯曲约束

当前代码没有直接使用微分曲率：

\[
\kappa(t)=
\frac{
|x'(t)y''(t)-y'(t)x''(t)|
}{
\left(
x'(t)^2+y'(t)^2
\right)^{3/2}
}
\]

而是采用归一化弓高作为曲率代理。

设根尖弦段为 \(\overline{\mathbf R\mathbf E}\)，则：

\[
\hat\kappa=
\frac{
\max_{\mathbf X\in C_{\text{sample}}}
d
\left(
\mathbf X,
\overline{\mathbf R\mathbf E}
\right)
}{
\|\mathbf E-\mathbf R\|
}
\]

其中 \(C_{\text{sample}}\) 是曲线采样点集合。

单条曲线要求：

\[
\hat\kappa\le0.25
\]

同时设置整体曲率覆盖率：

\[
\#\left\{
\text{free L1}\mid
0.055\le\hat\kappa\le0.20
\right\}
\ge4
\]

\[
\#\left\{
L2\mid
0.05\le\hat\kappa\le0.20
\right\}
\ge9
\]

\[
\#\left\{
L3\mid
0.05\le\hat\kappa\le0.20
\right\}
\ge1
\]

弯曲拓扑还必须满足：

\[
\text{bend count}\le2
\]

\[
\text{curvature sign reversal count}\le1
\]

因此当前曲率不是一个被直接优化的独立参数，而是由以下变量共同形成：

- 入口开口角；
- 行进方向；
- 出口释放角；
- 控制柄比例；
- C/S 模式；
- 根点和终点相对位置。

---

## 12. 结构和场景验证

验证是只读的：

\[
\operatorname{Valid}(C)=
\bigwedge_k g_k(C)
\]

验证前后的几何哈希必须相同：

\[
\operatorname{hash}(C_{\text{before}})
=
\operatorname{hash}(C_{\text{after}})
\]

### 12.1 层级约束

\[
(N_1,N_2,N_3)=(7,12,2)
\]

\[
level(child)=level(parent)+1
\]

\[
0<m<0.8
\]

子枝不能挂在父枝尖端，也不能被当作父枝的延续。

### 12.2 开口角约束

子枝入口切向与父局部切向的夹角必须满足：

\[
34^\circ\le
\angle
\left(
\mathbf T^{in},
\boldsymbol\tau
\right)
\le70^\circ
\]

子枝根尖 chord 与父局部切向的夹角必须满足：

\[
30^\circ\le
\angle
\left(
\mathbf E-\mathbf R,
\boldsymbol\tau
\right)
\le150^\circ
\]

### 12.3 父枝和主干净距

离开根部允许接触区后，子枝到父枝的距离必须满足：

\[
d_{\text{parent}}
\ge
\frac{
w_{\text{child}}+w_{\text{parent}}
}{2}
+0.8
\]

二级、三级枝到主干的距离必须满足：

\[
d_{\text{backbone}}
\ge
\frac{
w_{\text{child}}+w_{\text{backbone}}
}{2}
+0.8
\]

其中主干验证宽度取：

\[
w_{\text{backbone}}=5.0
\]

### 12.4 曲线间净距

两条曲线之间的最小中心线距离必须满足：

\[
d_{ij}
\ge
\frac{w_i+w_j}{2}
+1.0
\]

父子曲线仅在注册根点附近允许接触。

### 12.5 边缘验证

注册边缘枝必须满足：

\[
\|\mathbf E-\mathbf E_{\text{target}}\|
\le10^{-5}
\]

可见线宽与目标边缘的误差必须满足：

\[
d_{\text{boundary}}\le0.5
\]

终端切向与边缘平行方向之间的误差必须满足：

\[
\angle
\left(
\mathbf T^{out},
(\pm1,0)
\right)
\le5^\circ
\]

非注册枝不能接触上、下边缘带。

### 12.6 全局边缘覆盖

五个非花位 Unit 必须全部具有 frontier 路径：

\[
\#U_{\text{frontier}}=5
\]

上边缘目标数量：

\[
N_{\text{top}}=3
\]

下边缘目标数量：

\[
N_{\text{bottom}}=2
\]

上边缘相邻槽位间距：

\[
\Delta X_{\text{top}}\ge24
\]

下边缘两个槽位间距：

\[
\Delta X_{\text{bottom}}\ge12
\]

### 12.7 其他硬约束

还包括：

- 曲线不得自交；
- 每条曲线最多两个三次 Bézier 段；
- 两段曲线必须满足 \(C^0\) 和 \(C^1\) 连续；
- 控制柄不能退化；
- 花位枝不能提前进入花位椭圆；
- 非目标枝不能侵入任一花位；
- 可见线宽不能越过全局上下包络；
- Unit 内双子枝的挂载和方向必须具有足够分离；
- 五条一级枝不能连续全部朝同一侧。

---

## 13. seed 变化与可重放验证

当前开发 seed 为：

\[
z\in\{4101,4102,4103\}
\]

同一 seed 必须精确重放：

\[
C(P_0,z)=C(P_0,z)
\]

不同 seed 不仅要求几何哈希不同，还要求出现可见变化，包括：

- 六条可移动 L1 的挂载位置变化；
- 12 条 L2 的挂载比例变化；
- 2 条 L3 的挂载比例变化；
- 子枝在父枝上的相对滑移；
- 方向、长度和形状变化。

波谷花位枝 **primary_4_flower_1** 是窄带锚点，因此不承担与其他六条 L1 相同的挂载变化门槛。

---

## 14. 当前方法中真正固定、真正变化和外部控制的量

### 14.1 固定量

- \(7/12/2\) 拓扑；
- 曲线 ID；
- 父子 lineage；
- 每个角色的层级和责任；
- opening、length、travel angle 的角色区间；
- 双子枝中心状态表；
- near/far 身份；
- 双子枝挂载间隔 0.20；
- 五个 frontier 角色；
- top 3、bottom 2 的边缘责任；
- Bézier 构造公式；
- 层级线宽；
- 验证阈值。

### 14.2 随 seed 变化的量

- L1、L2、L3 挂载状态和 jitter；
- 开口角；
- 自由子枝的全局行进角；
- 弦长；
- 控制柄比例；
- 出口释放角；
- C/S 模式；
- 上下边缘带位置；
- frontier 横向槽位；
- 两条内部一级枝的目标点；
- 父枝变化所引起的后代根点和局部切向变化。

### 14.3 外部控制量

全局节奏偏移：

\[
\text{rhythm\_shift}\in[-0.04,0.04]
\]

默认：

\[
\text{rhythm\_shift}=0
\]

全局长度缩放：

\[
\text{length\_scale}\in[0.85,1.15]
\]

默认：

\[
\text{length\_scale}=1
\]

子树 flow：

\[
\text{flow}\in[-1,1]
\]

默认：

\[
\text{flow}=0
\]

---

## 15. 当前实现的真实边界

当前方法已经实现：

1. 固定深度的真实父子层级；
2. 每个 Unit 对 L1 和 L2 的联合安排；
3. 两个 Unit 内加入 L3；
4. seed 改变挂载位置、方向、长度和形状；
5. 波谷花位枝的窄带锚定；
6. 五个非花位 Unit 分担上下边缘；
7. 边缘目标按线宽内缩；
8. 边缘终端切向与边缘平行；
9. 同一场景内的跨 Unit 碰撞验证；
10. 同 seed 精确重放和不同 seed 可见变化验证。

当前尚未实现：

1. 动态决定每个 Unit 的 L2/L3 数量；
2. 动态决定三级枝出现在哪个二级枝上；
3. 完整父局部坐标中的子枝方向生成；
4. Unit 根据邻近 Unit 和剩余空间主动调整；
5. 失败后的候选搜索、重新规划或自动修复；
6. 真正参与几何的统一全局节奏 latent；
7. 由视觉目标直接优化分支参数。

还需要明确三个代码事实：

- **global.rhythm** 当前只写入 latent summary，没有参与几何；
- **global.length** 当前只写入 latent summary，没有参与几何；
- **subtree_u** 被计算，但当前没有参与后代几何。

真正驱动 seed 变化的是大量按曲线和属性分别标记的 \(V(z,\ell)\)，而不是一个统一的低维全局 latent。

因此，当前方法最准确的定位是：

> 一套固定深度、角色模板驱动、具有部分局部协调和全局边缘分工的程序化层级枝组生成器。

它已经通过当前开发实验的结构有效性门槛，但该门槛不等同于最终纹样美学通过。

---

## 16. 当前实验输出

当前实验结果：

- [manifest.json](../../artifacts/runs/_scratch_whole_local_true_lateral_n12_v23/manifest.json)
- [contact_sheet.png](../../artifacts/runs/_scratch_whole_local_true_lateral_n12_v23/contact_sheet.png)
- [contact_sheet_debug.png](../../artifacts/runs/_scratch_whole_local_true_lateral_n12_v23/contact_sheet_debug.png)
- [contact_sheet_units.png](../../artifacts/runs/_scratch_whole_local_true_lateral_n12_v23/contact_sheet_units.png)
- [mount_position_chart.png](../../artifacts/runs/_scratch_whole_local_true_lateral_n12_v23/mount_position_chart.png)
- [proofs.json](../../artifacts/runs/_scratch_whole_local_true_lateral_n12_v23/proofs.json)

当前三个 seed：

\[
4101,\quad4102,\quad4103
\]

均通过结构验证和标准证明。当前 manifest 对最终视觉结论的表述仍为：

> final_pattern_aesthetics: not_claimed_by_this_gate

因此，当前结果可以证明固定深度 BranchUnit 的结构生成、层级关系、边缘分工和 seed 变化机制能够运行，但不能据此直接宣称完整纹样的最终审美质量已经成立。
