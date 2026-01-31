import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function App() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchData = async () => {
    try {
      setError(null);
      const response = await axios.get(`${API_URL}/api/referral-balances`);
      // Сортируем данные по убыванию долга
      const sortedData = [...response.data.data].sort((a, b) => (b.debt || 0) - (a.debt || 0));
      setData(sortedData);
      setLastUpdate(new Date());
      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
      console.error('Ошибка загрузки данных:', err);
    }
  };

  useEffect(() => {
    // Первая загрузка
    fetchData();

    // Автообновление каждую минуту
    const interval = setInterval(() => {
      fetchData();
    }, 600000); // 600000 мс = 10 минут

    return () => clearInterval(interval);
  }, []);

  const formatNumber = (num) => {
    return new Intl.NumberFormat('ru-RU', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(num);
  };

  // Вычисляем общие суммы
  const totalDebt = data.reduce((sum, item) => sum + (item.debt || 0), 0);
  const totalReferralBalance = data.reduce((sum, item) => sum + (item.total_referral_balance || 0), 0);

  return (
    <div className="App">
      <div className="container">
        <header className="header">
          <h1>Реферальные балансы</h1>
          {lastUpdate && (
            <p className="last-update">
              Последнее обновление: {lastUpdate.toLocaleTimeString('ru-RU')}
            </p>
          )}
        </header>

        {loading && <div className="loading">Загрузка данных...</div>}
        
        {error && (
          <div className="error">
            Ошибка загрузки данных: {error}
            <button onClick={fetchData} className="retry-btn">
              Повторить
            </button>
          </div>
        )}

        {!loading && !error && (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Юзер айди</th>
                  <th>Юзернейм</th>
                  <th>Долг по рефке</th>
                  <th>Сумма всех реферальных отчислений</th>
                </tr>
              </thead>
              <tbody>
                {data.length === 0 ? (
                  <tr>
                    <td colSpan="4" className="no-data">
                      Нет данных
                    </td>
                  </tr>
                ) : (
                  <>
                    {data.map((item, index) => (
                      <tr key={item.user_id || index}>
                        <td>{item.user_id}</td>
                        <td>{item.username || 'N/A'}</td>
                        <td className={item.debt >= 0 ? 'positive' : 'negative'}>
                          {formatNumber(item.debt)}
                        </td>
                        <td>{formatNumber(item.total_referral_balance)}</td>
                      </tr>
                    ))}
                    <tr className="total-row">
                      <td colSpan="2" className="total-label">
                        <strong>Итого:</strong>
                      </td>
                      <td className={`total-value ${totalDebt >= 0 ? 'positive' : 'negative'}`}>
                        <strong>{formatNumber(totalDebt)}</strong>
                      </td>
                      <td className="total-value">
                        <strong>{formatNumber(totalReferralBalance)}</strong>
                      </td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
